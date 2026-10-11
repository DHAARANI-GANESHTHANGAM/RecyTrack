import { useEffect, useState, type FormEvent } from "react";

import { humanize } from "../utils/format";

export interface FilterField {
  name: string;
  label: string;
  type?: "text" | "select" | "datetime";
  options?: string[];
  placeholder?: string;
}

interface Props {
  fields: FilterField[];
  values: Record<string, string>;
  onApply: (values: Record<string, string>) => void;
}

/** Edits a draft of the filters; the page only changes (and the URL updates) on Apply or Clear. */
export function FilterBar({ fields, values, onApply }: Props) {
  const [draft, setDraft] = useState(values);
  const valuesKey = JSON.stringify(values);
  // Follow the URL when it changes from outside (back button, links); compare by content, not identity.
  useEffect(() => setDraft(values), [valuesKey]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onApply(draft);
  };
  const clear = () => {
    const empty = Object.fromEntries(fields.map((f) => [f.name, ""]));
    setDraft(empty);
    onApply(empty);
  };

  return (
    <form className="filter-bar" onSubmit={submit} aria-label="Filters">
      {fields.map((f) => {
        const id = `filter-${f.name}`;
        const value = draft[f.name] ?? "";
        const set = (v: string) => setDraft((d) => ({ ...d, [f.name]: v }));
        return (
          <div className="field" key={f.name}>
            <label htmlFor={id}>{f.label}</label>
            {f.type === "select" ? (
              <select id={id} value={value} onChange={(e) => set(e.target.value)}>
                <option value="">Any</option>
                {(f.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {humanize(o)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                type={f.type === "datetime" ? "datetime-local" : "text"}
                value={value}
                placeholder={f.placeholder}
                onChange={(e) => set(e.target.value)}
              />
            )}
          </div>
        );
      })}
      <div className="filter-actions">
        <button type="submit" className="primary">
          Apply filters
        </button>
        <button type="button" onClick={clear}>
          Clear
        </button>
      </div>
    </form>
  );
}
