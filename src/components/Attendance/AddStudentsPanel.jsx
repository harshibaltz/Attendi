import React, { useMemo, useState } from 'react';
import { Loader2, RefreshCw, Search, UserPlus } from 'lucide-react';
import attendanceApi from '../../lib/attendance';

const MAX_BATCH = 15;

const AddStudentsPanel = ({
  sessionId,
  existingStudentIds = [],
  roster = [],
  rosterLoading = false,
  rosterError = '',
  onReloadRoster,
  onAdded,
  onCancel,
}) => {
  const [term, setTerm] = useState('');
  const [picked, setPicked] = useState([]);
  const [status, setStatus] = useState('PRESENT');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const available = useMemo(() => {
    const taken = new Set(existingStudentIds.map((id) => String(id)));
    return roster
      .filter((s) => !taken.has(String(s.id)))
      .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''));
  }, [roster, existingStudentIds]);

  const q = term.trim().toLowerCase();
  const visible = available.filter((s) => (
    !q
    || (s.full_name || '').toLowerCase().includes(q)
    || (s.student_number || '').toLowerCase().includes(q)
    || (s.email || '').toLowerCase().includes(q)
  ));

  const toggle = (studentId) => {
    const id = String(studentId);
    setError('');
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= MAX_BATCH) {
        setError(`You can add up to ${MAX_BATCH} students at once.`);
        return prev;
      }
      return [...prev, id];
    });
  };

  const selectVisible = () => {
    const room = MAX_BATCH - picked.length;
    if (room <= 0) {
      setError(`You can add up to ${MAX_BATCH} students at once.`);
      return;
    }
    const next = visible
      .map((s) => String(s.id))
      .filter((id) => !picked.includes(id))
      .slice(0, room);
    if (next.length < visible.length - picked.filter((id) => visible.some((s) => String(s.id) === id)).length) {
      setError(`Selection capped at ${MAX_BATCH} students per batch.`);
    }
    setPicked((prev) => [...prev, ...next]);
  };

  const submit = async () => {
    if (picked.length === 0) {
      setError('Select at least one student to add.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = await attendanceApi.manualAttendanceBatch(sessionId, picked, status);
      const created = result?.created || [];
      const skipped = result?.skipped || [];
      if (created.length === 0 && skipped.length > 0) {
        setError('Those students already have a record for this session.');
        setSaving(false);
        return;
      }
      onAdded?.(created, skipped);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not add the selected students.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border border-border-default bg-page-bg p-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-[160px] flex-1">
          <label className="fet-label">Add students (up to {MAX_BATCH} at once)</label>
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Search by name, matricule or email"
              className="fet-input pl-9"
            />
          </div>
        </div>
        <div className="w-full sm:w-40">
          <label className="fet-label">Status for all</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="fet-select">
            <option value="PRESENT">Present</option>
            <option value="LATE">Late</option>
            <option value="ABSENT">Absent</option>
            <option value="EXCUSED">Excused</option>
          </select>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11.5px] text-text-secondary">
          {rosterLoading
            ? 'Loading roster…'
            : `${available.length} not yet recorded${q ? ` · ${visible.length} match "${term}"` : ''} · ${picked.length} selected`}
        </span>
        {!rosterLoading && available.length > 0 ? (
          <div className="flex gap-3">
            <button type="button" onClick={selectVisible} className="text-[11.5px] text-primary hover:underline">
              Select all visible
            </button>
            <button type="button" onClick={() => setPicked([])} className="text-[11.5px] text-text-secondary hover:underline">
              Clear
            </button>
          </div>
        ) : null}
      </div>

      {rosterLoading ? (
        <div className="flex items-center justify-center gap-2 py-8 text-[12.5px] text-text-secondary">
          <Loader2 size={16} className="animate-spin" /> Loading the class roster…
        </div>
      ) : rosterError ? (
        <div className="py-4 text-center">
          <p className="text-[12.5px] text-danger">{rosterError}</p>
          {onReloadRoster ? (
            <button type="button" onClick={onReloadRoster} className="fet-btn-secondary mt-2 h-8 text-xs">
              <RefreshCw size={13} /> Retry
            </button>
          ) : null}
        </div>
      ) : available.length === 0 ? (
        <p className="py-6 text-center text-[12.5px] text-text-secondary">
          {roster.length === 0
            ? 'No students are enrolled in this class yet.'
            : 'Everyone on this roster already has a record for this session.'}
        </p>
      ) : (
        <div className="mt-2 max-h-60 space-y-1 overflow-y-auto pr-1">
          {visible.length === 0 ? (
            <p className="py-4 text-center text-[12.5px] text-text-secondary">No student matches that search.</p>
          ) : visible.map((s) => {
            const id = String(s.id);
            const checked = picked.includes(id);
            const atLimit = !checked && picked.length >= MAX_BATCH;
            return (
              <label
                key={id}
                className={`flex cursor-pointer items-center gap-3 rounded-md border border-border-default bg-surface p-2 transition-colors hover:border-primary ${atLimit ? 'opacity-60' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={atLimit}
                  onChange={() => toggle(id)}
                  className="h-4 w-4 accent-primary"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-text-primary">{s.full_name}</span>
                  <span className="mono block truncate text-[11.5px] text-text-secondary">
                    {s.student_number || 'no matricule'}{s.email ? ` · ${s.email}` : ''}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={saving || rosterLoading || picked.length === 0}
          className="fet-btn-primary"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
          {saving ? 'Adding…' : `Add ${picked.length || ''} student${picked.length === 1 ? '' : 's'}`}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} className="fet-btn-secondary">
          Cancel
        </button>
      </div>
    </div>
  );
};

export default AddStudentsPanel;
