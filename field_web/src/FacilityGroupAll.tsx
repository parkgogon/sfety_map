import type { FacilityGroup } from "./types";

export function FacilityGroupAll({groups, selected, onChange}: {
  groups: FacilityGroup[];
  selected: ReadonlySet<string>;
  onChange: (groups: Set<string>) => void;
}) {
  const count = groups.filter(group => selected.has(group.id)).length;
  const all = groups.length > 0 && count === groups.length;
  return <label className="facility-group-all">
    <input type="checkbox" checked={all} disabled={!groups.length}
      ref={input => { if (input) input.indeterminate = count > 0 && !all; }}
      onChange={() => onChange(new Set(all ? [] : groups.map(group => group.id)))} />
    <strong>전체</strong><b>{groups.reduce((sum, group) => sum + group.count, 0)}</b>
  </label>;
}
