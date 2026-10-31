import React, { useEffect, useMemo, useState } from 'react';
import { Users, Loader2, Check, Search, AlertCircle } from 'lucide-react';
import attendanceApi from '../../lib/attendance';

/**
 * Staff control for departmental course delegates: the students who may open
 * attendance for any class of this course. Class delegates are appointed per
 * offering elsewhere; this list is course-wide.
 */
const CourseDelegatesPanel = ({ courseId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState([]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await attendanceApi.courseDelegates(courseId);
      setData(payload);
      setSelected((payload.delegates || []).map((d) => String(d.id)));
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not load attendance delegates.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (courseId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  const candidates = useMemo(() => {
    const rows = [...(data?.candidates || [])];
    const known = new Set(rows.map((r) => String(r.id)));
    (data?.delegates || []).forEach((d) => {
      if (!known.has(String(d.id))) rows.push(d);
    });
    const term = query.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((r) => (
      (r.full_name || '').toLowerCase().includes(term)
      || (r.student_number || '').toLowerCase().includes(term)
      || (r.email || '').toLowerCase().includes(term)
    ));
  }, [data, query]);

  const toggle = (id) => {
    const key = String(id);
    setSelected((prev) => (
      prev.includes(key) ? prev.filter((v) => v !== key) : [...prev, key]
    ));
    setNotice('');
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const payload = await attendanceApi.setCourseDelegates(courseId, selected);
      setData(payload);
      setSelected((payload.delegates || []).map((d) => String(d.id)));
      setNotice('Attendance delegates updated.');
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not save attendance delegates.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fet-card p-5 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-text-primary flex items-center gap-2">
            <Users size={16} className="text-primary" /> Attendance delegates
          </h3>
          <p className="text-sm text-text-secondary mt-1">
            Students who may launch and run attendance for every class of this course.
          </p>
        </div>
        <button
          type="button"
          onClick={save}
          disabled={saving || loading || !data}
          className="fet-btn-primary flex items-center gap-2 shrink-0"
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      {error ? (
        <div className="flex items-center gap-2 text-sm text-danger">
          <AlertCircle size={15} /> {error}
          <button type="button" onClick={load} className="underline">Retry</button>
        </div>
      ) : null}
      {notice ? <p className="text-sm text-success">{notice}</p> : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-text-secondary py-3">
          <Loader2 size={15} className="animate-spin" /> Loading students…
        </div>
      ) : data ? (
        <>
          <div className="flex items-center justify-between text-xs text-text-secondary">
            <span>{selected.length} selected</span>
            <span>{candidates.length} enrolled student{candidates.length === 1 ? '' : 's'}</span>
          </div>
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, matricule or email"
              className="fet-input pl-9"
            />
          </div>
          <div className="max-h-64 overflow-y-auto divide-y divide-border-default rounded-xl border border-border-default">
            {candidates.length === 0 ? (
              <p className="p-4 text-sm text-text-secondary">No enrolled students found for this course.</p>
            ) : candidates.map((student) => {
              const active = selected.includes(String(student.id));
              return (
                <button
                  key={student.id}
                  type="button"
                  onClick={() => toggle(student.id)}
                  className={`w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-page-bg ${active ? 'bg-primary/5' : ''}`}
                >
                  <span className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 ${
                    active ? 'bg-primary border-primary text-white' : 'border-border-default'
                  }`}>
                    {active ? <Check size={13} /> : null}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-text-primary truncate">
                      {student.full_name || student.email}
                    </span>
                    <span className="block text-xs text-text-secondary truncate">
                      {student.student_number || 'No matricule'} · {student.email}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
};

export default CourseDelegatesPanel;
