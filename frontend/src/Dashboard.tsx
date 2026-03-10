import { useEffect, useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  PointElement,
} from 'chart.js';
import { Bar, Line } from 'react-chartjs-2';

// Register ChartJS components
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  PointElement
);

// API Response Types
interface ScoreBucket {
  bucket: string;
  count: number;
}

interface TimelinePoint {
  date: string;
  submissions: number;
}

interface PassRate {
  task: string;
  avg_score: number;
  attempts: number;
}

// Available labs
const LABS = [
  { id: 'lab-01', name: 'Lab 01' },
  { id: 'lab-02', name: 'Lab 02' },
  { id: 'lab-03', name: 'Lab 03' },
  { id: 'lab-04', name: 'Lab 04' },
];

export default function Dashboard() {
  const [selectedLab, setSelectedLab] = useState<string>(LABS[0].id);
  const [scores, setScores] = useState<ScoreBucket[]>([]);
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [passRates, setPassRates] = useState<PassRate[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Get auth token from localStorage
  const getToken = (): string | null => {
    return localStorage.getItem('api_key');
  };

  // Fetch all data when lab changes
  useEffect(() => {
    const fetchData = async () => {
      const token = getToken();
      if (!token) {
        setError('No authentication token found');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        // Fetch all endpoints in parallel
        const [scoresRes, timelineRes, passRatesRes] = await Promise.all([
          fetch(`/analytics/scores?lab=${selectedLab}`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(`/analytics/timeline?lab=${selectedLab}`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(`/analytics/pass-rates?lab=${selectedLab}`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);

        // Check if any request failed
        if (!scoresRes.ok || !timelineRes.ok || !passRatesRes.ok) {
          throw new Error('Failed to fetch data');
        }

        // Parse responses
        const [scoresData, timelineData, passRatesData] = await Promise.all([
          scoresRes.json() as Promise<ScoreBucket[]>,
          timelineRes.json() as Promise<TimelinePoint[]>,
          passRatesRes.json() as Promise<PassRate[]>,
        ]);

        setScores(scoresData);
        setTimeline(timelineData);
        setPassRates(passRatesData);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [selectedLab]);

  // Prepare chart data
  const scoreChartData = {
    labels: scores.map(item => item.bucket),
    datasets: [
      {
        label: 'Number of Submissions',
        data: scores.map(item => item.count),
        backgroundColor: 'rgba(54, 162, 235, 0.5)',
        borderColor: 'rgba(54, 162, 235, 1)',
        borderWidth: 1,
      },
    ],
  };

  const timelineChartData = {
    labels: timeline.map(item => item.date),
    datasets: [
      {
        label: 'Submissions per Day',
        data: timeline.map(item => item.submissions),
        borderColor: 'rgb(75, 192, 192)',
        backgroundColor: 'rgba(75, 192, 192, 0.5)',
        tension: 0.1,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
      },
    },
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-xl">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-xl text-red-600">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-8">Analytics Dashboard</h1>

      {/* Lab Selector */}
      <div className="mb-8">
        <label htmlFor="lab-select" className="block text-sm font-medium text-gray-700 mb-2">
          Select Lab
        </label>
        <select
          id="lab-select"
          value={selectedLab}
          onChange={(e) => setSelectedLab(e.target.value)}
          className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
        >
          {LABS.map((lab) => (
            <option key={lab.id} value={lab.id}>
              {lab.name}
            </option>
          ))}
        </select>
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        {/* Score Distribution Bar Chart */}
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-xl font-semibold mb-4">Score Distribution</h2>
          <div className="h-80">
            {scores.length > 0 ? (
              <Bar data={scoreChartData} options={chartOptions} />
            ) : (
              <p className="text-gray-500">No score data available</p>
            )}
          </div>
        </div>

        {/* Timeline Line Chart */}
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-xl font-semibold mb-4">Submissions Timeline</h2>
          <div className="h-80">
            {timeline.length > 0 ? (
              <Line data={timelineChartData} options={chartOptions} />
            ) : (
              <p className="text-gray-500">No timeline data available</p>
            )}
          </div>
        </div>
      </div>

      {/* Pass Rates Table */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Task Pass Rates</h2>
        {passRates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Task
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Average Score
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Attempts
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {passRates.map((item) => (
                  <tr key={item.task}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {item.task}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {item.avg_score.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {item.attempts}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500">No pass rate data available</p>
        )}
      </div>
    </div>
  );
}