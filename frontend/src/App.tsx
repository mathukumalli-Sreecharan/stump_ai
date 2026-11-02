import { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const API = 'http://localhost:8000/api';

type Stats = {
  total_tasks: number;
  validated_tasks: number;
  rejected_tasks: number;
  evaluations: number;
  target_failures: number;
  average_quality: number | null;
  overall_pass_rate: number | null;
};

type Task = {
  task_id: string;
  difficulty: string;
  title: string;
  validation_status: string;
  quality_score: number;
};

function errorMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
    return detail.message;
  }
  return 'Request failed';
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [topic, setTopic] = useState('lists and edge cases');

  async function refresh() {
    try {
      const [statsResponse, tasksResponse] = await Promise.all([
        fetch(`${API}/analytics`),
        fetch(`${API}/tasks`),
      ]);
      if (!statsResponse.ok || !tasksResponse.ok) {
        throw new Error('Backend request failed');
      }
      setStats(await statsResponse.json());
      setTasks(await tasksResponse.json());
      setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'API unavailable');
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function generate() {
    setBusy(true);
    try {
      const response = await fetch(`${API}/tasks/generate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ topic, difficulty: 'medium', count: 1 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data.detail));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Generation failed');
    } finally {
      setBusy(false);
    }
  }

  const cards: [string, number | string | null | undefined][] = [
    ['Tasks', stats?.total_tasks],
    ['Validated', stats?.validated_tasks],
    ['Rejected', stats?.rejected_tasks],
    ['Model failures', stats?.target_failures],
    ['Avg quality', stats?.average_quality ?? '—'],
    ['Pass rate', stats?.overall_pass_rate == null ? '—' : `${stats.overall_pass_rate}%`],
  ];

  return (
    <main>
      <header>
        <div>
          <small>LOCAL BENCHMARK WORKSPACE</small>
          <h1>ModelStump</h1>
          <p>Validated tasks. Measurable model failures.</p>
        </div>
        <span className="pill">OLLAMA · LOCAL</span>
      </header>
      {error && <div className="error">{error} <button onClick={() => void refresh()}>Retry</button></div>}
      <section className="cards">
        {cards.map(([label, value]) => (
          <article className="card" key={label}>
            <small>{label}</small>
            <strong>{value ?? '—'}</strong>
          </article>
        ))}
      </section>
      <section className="grid">
        <article className="panel">
          <h2>Generate a benchmark task</h2>
          <p>New tasks are accepted only after golden solution validation.</p>
          <label>
            Topic
            <input value={topic} onChange={(event) => setTopic(event.target.value)} />
          </label>
          <button className="primary" disabled={busy} onClick={() => void generate()}>
            {busy ? 'Generating and validating…' : 'Generate task'}
          </button>
        </article>
        <article className="panel">
          <h2>Workspace activity</h2>
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={[
              { name: 'Validated', count: stats?.validated_tasks ?? 0 },
              { name: 'Rejected', count: stats?.rejected_tasks ?? 0 },
              { name: 'Failures', count: stats?.target_failures ?? 0 },
            ]}>
              <CartesianGrid strokeDasharray="3 3" stroke="#253041" />
              <XAxis dataKey="name" stroke="#8793a7" />
              <YAxis allowDecimals={false} stroke="#8793a7" />
              <Tooltip />
              <Bar dataKey="count" fill="#39d3b0" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </article>
      </section>
      <section className="panel">
        <div className="row">
          <div>
            <h2>Recent tasks</h2>
            <p>Task records returned by the backend</p>
          </div>
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
        <div className="table">
          <div className="thead"><span>Task</span><span>Difficulty</span><span>Status</span><span>Quality</span></div>
          {tasks.slice(-10).reverse().map((task) => (
            <div className="tr" key={`${task.task_id}`}>
              <span><b>{task.title}</b><small>{task.task_id}</small></span>
              <span>{task.difficulty}</span>
              <span className={task.validation_status === 'passed' ? 'good' : 'muted'}>{task.validation_status}</span>
              <span>{task.quality_score}/100</span>
            </div>
          ))}
          {tasks.length === 0 && <p className="empty">No tasks yet. Generate one after configuring Ollama.</p>}
        </div>
      </section>
      <footer>ModelStump MVP · execution uses local subprocesses and is not a secure sandbox.</footer>
    </main>
  );
}
