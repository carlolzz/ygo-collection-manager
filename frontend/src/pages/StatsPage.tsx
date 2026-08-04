import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import { getStats } from "../api";
import { CHART_COLORS, ErrorNotice, Loading, formatCondition } from "../components/common";
import { useAsync } from "../hooks";
import type { Bucket } from "../types";

const AXIS = { stroke: "var(--text-faint)", fontSize: 11 };
// A fixed band, so the pie's two-row legend and the bars' one-row legend leave
// the same amount of room for the plot above them. 40px fits two rows of 11px.
const LEGEND = { wrapperStyle: { fontSize: 11 }, verticalAlign: "bottom" as const, height: 40 };
const TOOLTIP = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    fontSize: 12,
    color: "var(--text)",
  },
};

export default function StatsPage() {
  const { data, error, loading } = useAsync(getStats, []);

  if (loading) return <Loading what="statistics" />;
  if (error) return <ErrorNotice message={error} />;
  if (!data) return null;

  return (
    <div className="stack">
      <div className="tiles">
        <Tile
          value={data.total_copies}
          label="Total copies"
          note="Every card, counting duplicates"
        />
        <Tile
          value={data.distinct_cards}
          label="Distinct cards"
          note="Unique passcodes owned"
        />
        <Tile value={data.collection_rows} label="Ledger rows" note="Stacks in the export" />
        <Tile
          value={data.sets_represented}
          label="Sets represented"
          note="Distinct named printings"
        />
        <Tile
          value={data.copies_without_printing}
          label="Copies with no printing"
          note="Counted inside the total"
        />
      </div>

      <div className="grid-2">
        <ChartPanel title="Copies by condition" subtitle="Cardmarket order, best first">
          <BucketBars data={data.by_condition} labeller={formatCondition} />
        </ChartPanel>

        <ChartPanel title="Distinct cards by type">
          <BucketPie data={data.by_type} />
        </ChartPanel>

        <ChartPanel title="Copies by attribute">
          <BucketBars data={data.by_attribute} />
        </ChartPanel>
      </div>

      <div className="panel">
        <div className="panel-title">Cards you hold the most copies of</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Card</th>
                <th className="num">Copies</th>
                <th className="num">Entries</th>
                <th className="num">Printings</th>
              </tr>
            </thead>
            <tbody>
              {data.most_held.map((card) => (
                <tr key={card.passcode}>
                  <td>
                    <Link to={`/card/${card.passcode}`}>{card.name}</Link>
                  </td>
                  <td className="num">{card.total_copies}</td>
                  <td className="num">{card.row_count}</td>
                  <td className="num">{card.printing_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Tile({ value, label, note }: { value: number; label: string; note: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value.toLocaleString()}</div>
      <div className="tile-label">{label}</div>
      <div className="tile-note">{note}</div>
    </div>
  );
}

function ChartPanel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="panel chart-panel">
      <div className="panel-title">{title}</div>
      {subtitle && <div className="panel-subtitle">{subtitle}</div>}
      <div className="chart">{children}</div>
    </div>
  );
}

/** Bars always show both counts, so "count" is never ambiguous. */
function BucketBars({
  data,
  labeller = (k: string) => k,
}: {
  data: Bucket[];
  labeller?: (key: string) => string;
}) {
  const rows = data.map((b) => ({
    ...b,
    label: b.key ? labeller(b.key) : "unknown",
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ left: -20, bottom: 4 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...AXIS} interval={0} angle={-25} textAnchor="end" height={58} />
        <YAxis {...AXIS} allowDecimals={false} />
        <Tooltip {...TOOLTIP} cursor={{ fill: "var(--surface-2)" }} />
        <Legend {...LEGEND} />
        <Bar dataKey="total_copies" name="Copies" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
        <Bar
          dataKey="distinct_cards"
          name="Distinct cards"
          fill="var(--chart-2)"
          radius={[3, 3, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

function BucketPie({ data }: { data: Bucket[] }) {
  const rows = data.map((b) => ({ name: b.key ?? "unknown", value: b.distinct_cards }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={rows}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius="78%"
          strokeWidth={0}
        >
          {rows.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Pie>
        {/* Says which count it is — a bare number here would be ambiguous. */}
        <Tooltip {...TOOLTIP} formatter={(value) => [`${value} distinct cards`, ""]} />
        <Legend {...LEGEND} />
      </PieChart>
    </ResponsiveContainer>
  );
}
