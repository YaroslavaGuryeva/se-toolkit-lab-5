"""Router for analytics endpoints.

Each endpoint performs SQL aggregation queries on the interaction data
populated by the ETL pipeline. All endpoints require a `lab` query
parameter to filter results by lab (e.g., "lab-01").
"""

from fastapi import APIRouter, Depends, Query
from sqlmodel import select, func, case
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models.item import ItemRecord
from app.models.interaction import InteractionLog
from app.models.learner import Learner

router = APIRouter()


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Score distribution histogram for a given lab.
    
    - Find the lab item by matching title (e.g. "lab-04" → title contains "Lab 04")
    - Find all tasks that belong to this lab (parent_id = lab.id)
    - Query interactions for these items that have a score
    - Group scores into buckets: "0-25", "26-50", "51-75", "76-100"
      using CASE WHEN expressions
    - Return a JSON array with all four buckets
    """
    # Extract lab number from query (e.g., "lab-04" → "04")
    lab_number = lab.replace("lab-", "")
    
    # Find the lab item - use exec() instead of execute()
    lab_item_result = await session.exec(
        select(ItemRecord).where(
            ItemRecord.type == "lab",
            ItemRecord.title.contains(f"Lab {lab_number}")
        )
    )
    lab_item = lab_item_result.first()
    
    if not lab_item:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]
    
    # Find all tasks that belong to this lab
    tasks_result = await session.exec(
        select(ItemRecord.id).where(
            ItemRecord.type == "task",
            ItemRecord.parent_id == lab_item.id
        )
    )
    task_ids = tasks_result.all()
    
    if not task_ids:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]
    
    # Query interactions and group by score buckets
    # Fixed: Use case() as a standalone function, not under func
    result = await session.exec(
        select(
            case(
                (InteractionLog.score <= 25, "0-25"),
                (InteractionLog.score <= 50, "26-50"),
                (InteractionLog.score <= 75, "51-75"),
                else_="76-100"
            ).label("bucket"),
            func.count().label("count")
        )
        .where(
            InteractionLog.item_id.in_(task_ids),
            InteractionLog.score.isnot(None)
        )
        .group_by("bucket")
    )
    
    # Convert to dictionary for easy lookup
    counts = {row.bucket: row.count for row in result}
    
    # Return all four buckets in order
    return [
        {"bucket": "0-25", "count": counts.get("0-25", 0)},
        {"bucket": "26-50", "count": counts.get("26-50", 0)},
        {"bucket": "51-75", "count": counts.get("51-75", 0)},
        {"bucket": "76-100", "count": counts.get("76-100", 0)},
    ]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-task pass rates for a given lab.
    
    - Find the lab item and its child task items
    - For each task, compute avg_score and attempts count
    - Return ordered by task title
    """
    # Extract lab number from query
    lab_number = lab.replace("lab-", "")
    
    # Find the lab item
    lab_item_result = await session.exec(
        select(ItemRecord).where(
            ItemRecord.type == "lab",
            ItemRecord.title.contains(f"Lab {lab_number}")
        )
    )
    lab_item = lab_item_result.first()
    
    if not lab_item:
        return []
    
    # Query tasks with their statistics
    result = await session.exec(
        select(
            ItemRecord.title.label("task"),
            func.avg(InteractionLog.score).label("avg_score"),
            func.count(InteractionLog.id).label("attempts")
        )
        .join(InteractionLog, InteractionLog.item_id == ItemRecord.id, isouter=True)
        .where(
            ItemRecord.parent_id == lab_item.id,
            ItemRecord.type == "task"
        )
        .group_by(ItemRecord.id, ItemRecord.title)
        .order_by(ItemRecord.title)
    )
    
    # Format the response
    response = []
    for row in result:
        avg_score = row.avg_score
        if avg_score is not None:
            avg_score = round(avg_score, 1)
        else:
            avg_score = 0.0
            
        response.append({
            "task": row.task,
            "avg_score": avg_score,
            "attempts": row.attempts or 0
        })
    
    return response


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Submissions per day for a given lab.
    
    - Find the lab item and its child task items
    - Group interactions by date
    - Count submissions per day
    - Order by date ascending
    """
    # Extract lab number from query
    lab_number = lab.replace("lab-", "")
    
    # Find the lab item
    lab_item_result = await session.exec(
        select(ItemRecord).where(
            ItemRecord.type == "lab",
            ItemRecord.title.contains(f"Lab {lab_number}")
        )
    )
    lab_item = lab_item_result.first()
    
    if not lab_item:
        return []
    
    # Find all tasks that belong to this lab
    tasks_result = await session.exec(
        select(ItemRecord.id).where(
            ItemRecord.type == "task",
            ItemRecord.parent_id == lab_item.id
        )
    )
    task_ids = tasks_result.all()
    
    if not task_ids:
        return []
    
    # Group interactions by date
    result = await session.exec(
        select(
            func.date(InteractionLog.created_at).label("date"),
            func.count().label("submissions")
        )
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(func.date(InteractionLog.created_at))
        .order_by(func.date(InteractionLog.created_at))
    )
    
    # Format the response
    return [
        {"date": row.date, "submissions": row.submissions}
        for row in result
    ]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-group performance for a given lab.
    
    - Find the lab item and its child task items
    - Join interactions with learners to get student_group
    - For each group, compute avg_score and distinct student count
    - Order by group name
    """
    # Extract lab number from query
    lab_number = lab.replace("lab-", "")
    
    # Find the lab item
    lab_item_result = await session.exec(
        select(ItemRecord).where(
            ItemRecord.type == "lab",
            ItemRecord.title.contains(f"Lab {lab_number}")
        )
    )
    lab_item = lab_item_result.first()
    
    if not lab_item:
        return []
    
    # Find all tasks that belong to this lab
    tasks_result = await session.exec(
        select(ItemRecord.id).where(
            ItemRecord.type == "task",
            ItemRecord.parent_id == lab_item.id
        )
    )
    task_ids = tasks_result.all()
    
    if not task_ids:
        return []
    
    # Query group statistics
    result = await session.exec(
        select(
            Learner.student_group.label("group"),
            func.avg(InteractionLog.score).label("avg_score"),
            func.count(func.distinct(Learner.id)).label("students")
        )
        .join(InteractionLog, InteractionLog.learner_id == Learner.id)
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )
    
    # Format the response
    response = []
    for row in result:
        avg_score = row.avg_score
        if avg_score is not None:
            avg_score = round(avg_score, 1)
        else:
            avg_score = 0.0
            
        response.append({
            "group": row.group,
            "avg_score": avg_score,
            "students": row.students
        })
    
    return response