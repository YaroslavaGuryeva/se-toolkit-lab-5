"""ETL pipeline: fetch data from the autochecker API and load it into the database.

The autochecker dashboard API provides two endpoints:
- GET /api/items — lab/task catalog
- GET /api/logs  — anonymized check results (supports ?since= and ?limit= params)

Both require HTTP Basic Auth (email + password from settings).
"""

from datetime import datetime

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.settings import settings


# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------


async def fetch_items() -> list[dict]:
    """Fetch the lab/task catalog from the autochecker API.

    This function connects to the external autochecker API and retrieves
    the catalog of labs and tasks available in the course.

    How it works:
    1. We create an async HTTP client using httpx.AsyncClient
    2. We send a GET request to the /api/items endpoint
    3. We pass HTTP Basic Auth credentials (email + password) from settings
    4. We verify the response status is 200 (OK)
    5. We parse and return the JSON response as a list of dictionaries

    Each item in the response has this structure:
    - lab: str - the lab identifier (e.g., "lab-01")
    - task: str | null - the task identifier (e.g., "setup") or null for labs
    - title: str - human-readable title (e.g., "Lab 01 – Repository Setup")
    - type: "lab" | "task" - the item type

    Returns:
        list[dict]: A list of item dictionaries from the API

    Raises:
        httpx.HTTPStatusError: If the response status is not 200
        httpx.RequestError: If the network request fails
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url=f"{settings.autochecker_api_url}/api/items",
            auth=(settings.autochecker_email, settings.autochecker_password),
        )
        response.raise_for_status()
        return response.json()


async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Fetch check results from the autochecker API with pagination.

    This function retrieves anonymized check logs from the autochecker API.
    It supports incremental sync by fetching only logs submitted after a
    given timestamp.

    How it works:
    1. We create an async HTTP client using httpx.AsyncClient
    2. We send GET requests to /api/logs with limit=500 (batch size)
    3. If `since` is provided, we add it as a query parameter for incremental sync
    4. We pass HTTP Basic Auth credentials from settings
    5. The API returns a paginated response: {"logs": [...], "has_more": bool}
    6. While has_more is True, we continue fetching the next page
    7. For each subsequent page, we update `since` to the last log's submitted_at
    8. We combine all logs from all pages into a single list

    Why pagination?
    - The API may have thousands of logs; fetching all at once would be slow
    - Pagination allows us to fetch data in manageable batches (500 at a time)
    - Incremental sync (using `since`) lets us fetch only new data since last run

    Args:
        since: Optional datetime - fetch only logs submitted after this time.
               If None, fetches all logs from the beginning.

    Returns:
        list[dict]: A combined list of all log dictionaries from all pages.
                    Each log has: id, student_id, group, lab, task, score,
                    passed, failed, total, checks, submitted_at

    Raises:
        httpx.HTTPStatusError: If the response status is not 200
        httpx.RequestError: If the network request fails
    """
    all_logs: list[dict] = []
    current_since: datetime | None = since

    async with httpx.AsyncClient() as client:
        while True:
            params: dict[str, str | int] = {"limit": 500}
            if current_since is not None:
                params["since"] = current_since.isoformat()

            response = await client.get(
                url=f"{settings.autochecker_api_url}/api/logs",
                params=params,
                auth=(settings.autochecker_email, settings.autochecker_password),
            )
            response.raise_for_status()
            data = response.json()

            logs: list[dict] = data.get("logs", [])
            all_logs.extend(logs)

            if not data.get("has_more", False):
                break

            # Update since to the last log's submitted_at for the next page
            if logs:
                last_submitted_at = logs[-1].get("submitted_at")
                if last_submitted_at:
                    current_since = datetime.fromisoformat(last_submitted_at.replace("Z", "+00:00"))

    return all_logs


# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------


async def load_items(items: list[dict], session: AsyncSession) -> int:
    from app.models.item import ItemRecord

    new_items_count = 0
    lab_map: dict[str, ItemRecord] = {}

    # Process labs first
    for item in items:
        if item.get("type") == "lab":
            lab_title = item.get("title")
            lab_short_id = item.get("lab")

            # Check if lab already exists - АСИНХРОННО!
            result = await session.execute(
                select(ItemRecord)
                .where(ItemRecord.type == "lab")
                .where(ItemRecord.title == lab_title)
            )
            existing_lab = result.scalar_one_or_none()

            if existing_lab is None:
                new_lab = ItemRecord(
                    type="lab",
                    title=lab_title,
                    description="",
                    attributes={},
                )
                session.add(new_lab)
                await session.flush()
                lab_map[lab_short_id] = new_lab
                new_items_count += 1
            else:
                lab_map[lab_short_id] = existing_lab

    # Process tasks
    for item in items:
        if item.get("type") == "task":
            task_title = item.get("title")
            lab_short_id = item.get("lab")

            parent_lab = lab_map.get(lab_short_id)
            if parent_lab is None:
                continue

            # Check if task already exists - АСИНХРОННО!
            result = await session.execute(
                select(ItemRecord)
                .where(ItemRecord.type == "task")
                .where(ItemRecord.title == task_title)
                .where(ItemRecord.parent_id == parent_lab.id)
            )
            existing_task = result.scalar_one_or_none()

            if existing_task is None:
                new_task = ItemRecord(
                    type="task",
                    title=task_title,
                    description="",
                    parent_id=parent_lab.id,
                    attributes={},
                )
                session.add(new_task)
                new_items_count += 1

    await session.commit()
    return new_items_count

#=========================================================

#======================================================
async def load_logs(
    logs: list[dict], items_catalog: list[dict], session: AsyncSession
) -> int:
    """Load interaction logs into the database."""
    from app.models.learner import Learner
    from app.models.interaction import InteractionLog
    from app.models.item import ItemRecord

    new_interactions_count = 0

    # Build lookup from (lab_short_id, task_short_id) to item info (title and type)
    item_info_map: dict[tuple[str, str | None], tuple[str, str]] = {}
    for item in items_catalog:
        lab_short_id = item.get("lab")
        task_short_id = item.get("task")  # None for labs
        title = item.get("title")
        item_type = item.get("type")  # "lab" or "task"
        item_info_map[(lab_short_id, task_short_id)] = (title, item_type)

    for log in logs:
        # 1. Find or create Learner
        student_id = log.get("student_id")
        student_group = log.get("group", "")

        result = await session.execute(
            select(Learner).where(Learner.external_id == student_id)
        )
        learner = result.scalar_one_or_none()

        if learner is None:
            learner = Learner(
                external_id=student_id,
                student_group=student_group,
            )
            session.add(learner)
            await session.flush()

        # 2. Find the matching item in the database
        lab_short_id = log.get("lab")
        task_short_id = log.get("task")

        # Get item info (title and type) from the map
        item_info = item_info_map.get((lab_short_id, task_short_id))
        if item_info is None:
            continue

        item_title, item_type = item_info

        # Build query with both title and type to avoid duplicates
        query = select(ItemRecord).where(
            ItemRecord.title == item_title,
            ItemRecord.type == item_type
        )

        # For tasks, also filter by parent_id to be extra safe
        if item_type == "task":
            # Find the parent lab first
            parent_lab_info = item_info_map.get((lab_short_id, None))
            if parent_lab_info:
                parent_title, _ = parent_lab_info
                parent_result = await session.execute(
                    select(ItemRecord).where(
                        ItemRecord.title == parent_title,
                        ItemRecord.type == "lab"
                    )
                )
                parent_lab = parent_result.scalar_one_or_none()
                if parent_lab:
                    query = query.where(ItemRecord.parent_id == parent_lab.id)

        result = await session.execute(query)
        
        # Use first() instead of scalar_one_or_none() to handle multiple results
        # In case of duplicates, take the first one
        items = result.scalars().all()
        if not items:
            continue
            
        item = items[0]  # Take first if multiple found
        if len(items) > 1:
            # Log warning about duplicates (optional)
            print(f"Warning: Multiple items found with title '{item_title}' and type '{item_type}'")

        # 3. Check if InteractionLog already exists
        log_external_id = log.get("id")
        result = await session.execute(
            select(InteractionLog).where(InteractionLog.external_id == log_external_id)
        )
        existing_interaction = result.scalar_one_or_none()

        if existing_interaction is not None:
            continue

        # 4. Create new InteractionLog
        submitted_at_str = log.get("submitted_at")
        submitted_at = None
        if submitted_at_str:
            submitted_at = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))

        new_interaction = InteractionLog(
            external_id=log_external_id,
            learner_id=learner.id,
            item_id=item.id,
            kind="attempt",
            score=log.get("score"),
            checks_passed=log.get("passed"),
            checks_total=log.get("total"),
            created_at=submitted_at,
        )
        session.add(new_interaction)
        new_interactions_count += 1

    await session.commit()
    return new_interactions_count

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync(session: AsyncSession) -> dict:
    from app.models.interaction import InteractionLog

    # Step 1: Fetch items from the API and load them into the database
    items_catalog = await fetch_items()
    await load_items(items=items_catalog, session=session)

    # Step 2: Determine the last synced timestamp - FIXED
    result = await session.execute(
        select(InteractionLog).order_by(InteractionLog.created_at.desc()).limit(1)
    )
    latest_interaction = result.scalar_one_or_none()  # Now safe because we limited to 1 row

    since: datetime | None = None
    if latest_interaction is not None:
        since = latest_interaction.created_at

    # Step 3: Fetch logs since that timestamp and load them
    logs = await fetch_logs(since=since)
    new_interactions = await load_logs(
        logs=logs,
        items_catalog=items_catalog,
        session=session,
    )

    # Step 4: Get total count of interactions - FIXED
    result = await session.execute(select(InteractionLog))
    total_interactions = len(result.scalars().all())  # This is fine, we want all rows here

    return {
        "new_records": new_interactions,
        "total_records": total_interactions,
    }