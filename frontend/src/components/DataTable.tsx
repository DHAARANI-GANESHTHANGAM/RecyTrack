import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  /** "num" right-aligns numbers so digits line up. */
  className?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  caption?: ReactNode;
  /** Optional whole-row click. Put a real link in one cell as well so keyboard users can open it. */
  onRowClick?: (row: T) => void;
}

/** A plain <table> that scrolls sideways inside its own box on narrow screens. */
export function DataTable<T>({ columns, rows, rowKey, caption, onRowClick }: Props<T>) {
  return (
    <div className="table-wrap">
      <table>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.header} scope="col" className={c.className}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "clickable" : undefined}
              onClick={
                onRowClick
                  ? (e) => {
                      // Let links and buttons inside the row do their own thing.
                      if (!(e.target as HTMLElement).closest("a, button")) onRowClick(row);
                    }
                  : undefined
              }
            >
              {columns.map((c) => (
                <td key={c.header} className={c.className}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
