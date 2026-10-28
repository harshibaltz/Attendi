import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Building2, CalendarRange, Plus, Check, X, BookOpen, UserCheck, ChevronDown } from 'lucide-react';
import { SectionHeader, Card, CardBody, CardHead, DataTable, Pill, Callout, EmptyState, Tabs } from '../UI';
import { academicsApi } from '../../lib/academics';
import { errorMessage } from '../../lib/enrollment';
import { formatDate } from '../../lib/format';

const SemesterPanel = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setRows((await academicsApi.semesters()) || []);
    } catch (err) {
      setError(errorMessage(err, 'Could not load semesters.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const activate = async (semester) => {
    setBusy(semester.id);
    setError('');
    setNotice('');
    try {
      await academicsApi.activateSemester(semester.id);
      setNotice(`${semester.name} is now the active semester.`);
      await load();
    } catch (err) {
      setError(errorMessage(err, 'Could not activate that semester.'));
    } finally {
      setBusy('');
    }
  };

  const columns = [
    { key: 'name', label: 'Semester' },
    { key: 'academic_year', label: 'Year', width: '110px' },
    { key: 'number', label: 'No.', width: '70px' },
    { key: 'start_date', label: 'Starts', width: '130px', render: (r) => formatDate(r.start_date) },
    { key: 'end_date', label: 'Ends', width: '130px', render: (r) => formatDate(r.end_date) },
    {
      key: 'registration_deadline',
      label: 'Registration closes',
      width: '160px',
      render: (r) => (r.registration_deadline ? formatDate(r.registration_deadline) : '—'),
    },
    {
      key: 'is_active',
      label: 'State',
      width: '190px',
      render: (r) => (r.is_active
        ? <Pill tone="ok" dot>Active</Pill>
        : <button
            type="button"
            onClick={() => activate(r)}
            disabled={busy === r.id}
            className="fet-btn-secondary text-[12px]"
          >
            <Check size={13} /> {busy === r.id ? 'Activating...' : 'Make active'}
          </button>),
    },
  ];

  return (
    <div className="space-y-4">
      {error ? <Callout tone="bad">{error}</Callout> : null}
      {notice ? <Callout tone="ok">{notice}</Callout> : null}

      <Callout tone="in">
        Exactly one semester is active at a time. Course registration, enrolment and
        carry-over all read the active semester, so activating the wrong one closes
        student registration for the whole faculty.
      </Callout>

      <Card accent="hub">
        <CardHead title="Semesters" square="hub" />
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            empty={loading
              ? <p className="text-text-secondary text-[13px] py-6 text-center">Loading semesters...</p>
              : <EmptyState icon={CalendarRange} title="No semesters yet" subtitle="Create one to open registration." />}
          />
        </CardBody>
      </Card>
    </div>
  );
};

const DepartmentPanel = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ code: '', name: '', faculty: '', description: '' });

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setRows((await academicsApi.departments()) || []);
    } catch (err) {
      setError(errorMessage(err, 'Could not load departments.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await academicsApi.createDepartment({
        code: form.code.trim().toUpperCase(),
        name: form.name.trim(),
        faculty: form.faculty,
        description: form.description.trim(),
      });
      setForm({ code: '', name: '', faculty: '', description: '' });
      setShowForm(false);
      await load();
    } catch (err) {
      setError(errorMessage(err, 'Could not create that department.'));
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'code', label: 'Code', width: '100px', render: (r) => <b className="num">{r.code}</b> },
    { key: 'name', label: 'Department' },
    { key: 'faculty_name', label: 'Faculty', render: (r) => r.faculty_name || '—' },
    {
      key: 'status',
      label: 'State',
      width: '110px',
      render: (r) => <Pill tone={r.status === 'ACTIVE' ? 'ok' : 'mute'}>{r.status}</Pill>,
    },
  ];

  return (
    <div className="space-y-4">
      {error ? <Callout tone="bad">{error}</Callout> : null}

      <Card accent="hub">
        <CardHead title="Departments" square="hub">
          <button type="button" onClick={() => setShowForm((v) => !v)} className="fet-btn-primary text-[12px]">
            {showForm ? <X size={14} /> : <Plus size={14} />}
            {showForm ? 'Cancel' : 'New department'}
          </button>
        </CardHead>
        <CardBody>
          {showForm ? (
            <form onSubmit={submit} className="space-y-3 mb-5 p-4 rounded-lg bg-page-bg">
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="fet-label">Code</label>
                  <input
                    className="fet-input"
                    value={form.code}
                    onChange={(e) => setForm({ ...form, code: e.target.value })}
                    placeholder="CS"
                    required
                  />
                </div>
                <div>
                  <label className="fet-label">Name</label>
                  <input
                    className="fet-input"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Computer Science"
                    required
                  />
                </div>
              </div>
              <div>
                <label className="fet-label">Faculty</label>
                <input
                  className="fet-input"
                  value={form.faculty}
                  onChange={(e) => setForm({ ...form, faculty: e.target.value })}
                  placeholder="Faculty UUID"
                />
              </div>
              <div>
                <label className="fet-label">Description</label>
                <input
                  className="fet-input"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
              <div className="flex justify-end">
                <button type="submit" className="fet-btn-primary" disabled={busy}>
                  {busy ? 'Creating...' : 'Create department'}
                </button>
              </div>
            </form>
          ) : null}

          <DataTable
            columns={columns}
            rows={rows}
            empty={loading
              ? <p className="text-text-secondary text-[13px] py-6 text-center">Loading departments...</p>
              : <EmptyState icon={Building2} title="No departments yet" subtitle="Students cannot register until a department exists." />}
          />
        </CardBody>
      </Card>
    </div>
  );
};

const _initials = (name = '') =>
  name.trim().split(/\s+/).map((word) => word[0] || '').join('').toLowerCase();

const teacherMatches = (lecturer, query) => {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const name = (lecturer.full_name || '').toLowerCase();
  const email = (lecturer.email || '').toLowerCase();
  if (name.includes(q) || email.includes(q)) return true;
  const compact = q.replace(/[^a-z0-9]/g, '');
  if (compact && _initials(name).startsWith(compact)) return true;
  const words = name.split(/\s+/);
  return q.split(/\s+/).every((part) => words.some((word) => word.startsWith(part)));
};

/** Searchable lecturer picker: name, email, "JL" initials or "jo do". */
const TeacherPicker = ({ value, lecturers, onChange, excludeId, label, placeholder }) => {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState('');
  const rootRef = useRef(null);
  const selected = lecturers.find((item) => item.id === value) || null;

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const matches = useMemo(
    () => lecturers.filter((item) => item.id !== excludeId && teacherMatches(item, term)),
    [lecturers, excludeId, term],
  );

  const choose = (id) => {
    onChange(id);
    setOpen(false);
    setTerm('');
  };

  return (
    <div ref={rootRef} className="min-w-[220px]">
      <button
        type="button"
        aria-label={label}
        onClick={() => setOpen((current) => !current)}
        className="fet-input flex w-full items-center justify-between gap-2 text-left"
      >
        <span className={selected ? 'truncate' : 'truncate text-text-secondary'}>
          {selected ? selected.full_name : placeholder}
        </span>
        <ChevronDown size={14} className="shrink-0 text-text-secondary" />
      </button>
      {open ? (
        <div className="mt-1 rounded-md border border-border-default bg-surface p-2">
          <input
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search name, email or initials"
            aria-label={`Search ${label}`}
            className="fet-input mb-2 w-full"
          />
          <div className="max-h-44 overflow-y-auto">
            <button
              type="button"
              onClick={() => choose('')}
              className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text-secondary hover:bg-surface-2"
            >
              Unassigned
            </button>
            {matches.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => choose(item.id)}
                className={`block w-full rounded px-2 py-1.5 text-left hover:bg-surface-2 ${item.id === value ? 'font-semibold' : ''}`}
              >
                <span className="block text-[13px] text-text-primary">{item.full_name}</span>
                <span className="block text-[11px] text-text-secondary">{item.email}</span>
              </button>
            ))}
            {!matches.length ? (
              <p className="px-2 py-2 text-[12px] text-text-secondary">No lecturer matches.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};

/** Owning department is inherent; the checked list adds departments whose
 *  students may also self-register for the offering. */
const DepartmentPicker = ({ value, departments, primaryId, onChange, label }) => {
  const selected = new Set(value);
  const shared = value.filter((id) => id !== String(primaryId));
  const toggle = (id) => {
    const next = new Set(value);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange([...next]);
  };
  return (
    <details className="min-w-[190px]">
      <summary
        aria-label={label}
        className="fet-input flex cursor-pointer list-none items-center justify-between gap-2"
      >
        <span>{shared.length ? `${shared.length} shared` : 'Owning only'}</span>
        <ChevronDown size={14} className="shrink-0 text-text-secondary" />
      </summary>
      <div className="mt-1 max-h-44 overflow-y-auto rounded-md border border-border-default bg-surface p-2">
        <p className="mb-1 text-[11px] text-text-secondary">
          Students in checked departments may also register.
        </p>
        {departments.map((department) => {
          const id = String(department.id);
          const isPrimary = id === String(primaryId);
          return (
            <label
              key={id}
              className="flex items-center gap-2 rounded px-1 py-1 text-[12px] hover:bg-surface-2"
            >
              <input
                type="checkbox"
                checked={isPrimary || selected.has(id)}
                disabled={isPrimary}
                onChange={() => toggle(id)}
              />
              <span className="truncate">{department.name}</span>
              {isPrimary ? (
                <span className="ml-auto text-[10px] uppercase text-text-secondary">Owning</span>
              ) : null}
            </label>
          );
        })}
      </div>
    </details>
  );
};

const draftFor = (row) => ({
  lecturer: row.lecturer || '',
  co_lecturer: row.co_lecturer || '',
  departments: (row.departments || []).map(String).filter((id) => id !== String(row.department)),
});

const CourseOfferingPanel = () => {
  const [rows, setRows] = useState([]);
  const [lecturers, setLecturers] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [activeSemester, setActiveSemester] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [offerings, lecturerRows, semesterRows, departmentRows] = await Promise.all([
        academicsApi.courseOfferings(),
        academicsApi.lecturers(),
        academicsApi.semesters(),
        academicsApi.departments(),
      ]);
      const active = (semesterRows || []).find((semester) => semester.is_active) || null;
      setActiveSemester(active);
      // The current term is what admins touch most, so list it first; the
      // assigned lecturer sees every offering either way.
      const offeringRows = [...(offerings || [])].sort((a, b) => {
        const aActive = active && a.semester === active.id ? 0 : 1;
        const bActive = active && b.semester === active.id ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;
        return (a.course_code || '').localeCompare(b.course_code || '');
      });
      setRows(offeringRows);
      setLecturers(lecturerRows || []);
      setDepartments(departmentRows || []);
      setDrafts(Object.fromEntries(offeringRows.map((row) => [row.id, draftFor(row)])));
    } catch (err) {
      setError(errorMessage(err, 'Could not load course offerings and lecturers.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const draftOf = (row) => drafts[row.id] || draftFor(row);

  const updateDraft = (row, patch) =>
    setDrafts((current) => ({ ...current, [row.id]: { ...draftOf(row), ...patch } }));

  const isDirty = (row) => {
    const draft = draftOf(row);
    const original = draftFor(row);
    const sameSet = (a, b) =>
      [...a].sort().join('|') === [...b].sort().join('|');
    return (
      draft.lecturer !== original.lecturer ||
      draft.co_lecturer !== original.co_lecturer ||
      !sameSet(draft.departments, original.departments)
    );
  };

  const save = async (row) => {
    const draft = draftOf(row);
    if (draft.lecturer && draft.lecturer === draft.co_lecturer) {
      setNotice('');
      setError('The lead lecturer cannot also be the co-lecturer.');
      return;
    }
    setBusyId(row.id);
    setError('');
    setNotice('');
    try {
      await academicsApi.updateOffering(row.id, {
        lecturer: draft.lecturer || null,
        co_lecturer: draft.co_lecturer || null,
        departments: draft.departments,
      });
      setNotice(`${row.course_code} updated.`);
      await load();
    } catch (err) {
      setError(errorMessage(err, `Could not update ${row.course_code}.`));
    } finally {
      setBusyId('');
    }
  };

  const unassigned = rows.filter((row) => !row.lecturer).length;
  const columns = [
    {
      key: 'course_code',
      label: 'Course',
      render: (row) => (
        <div className="min-w-[180px]">
          <p className="font-semibold text-text-primary">{row.course_code}</p>
          <p className="text-xs text-text-secondary">{row.course_title}</p>
        </div>
      ),
    },
    { key: 'department_name', label: 'Owning department' },
    {
      key: 'semester_name',
      label: 'Semester',
      render: (row) => (
        <div className="flex min-w-[150px] items-center gap-2">
          <span>{row.semester_name || '—'}</span>
          {!activeSemester ? null : row.semester === activeSemester.id
            ? <Pill tone="ok" dot>Active</Pill>
            : <Pill tone="wn">Not active</Pill>}
        </div>
      ),
    },
    {
      key: 'lecturer',
      label: 'Lead lecturer',
      render: (row) => {
        const draft = draftOf(row);
        return (
          <TeacherPicker
            value={draft.lecturer}
            lecturers={lecturers}
            excludeId={draft.co_lecturer}
            label={`Lead lecturer for ${row.course_code}`}
            placeholder="Unassigned"
            onChange={(id) => updateDraft(row, {
              lecturer: id,
              ...(id && id === draft.co_lecturer ? { co_lecturer: '' } : {}),
            })}
          />
        );
      },
    },
    {
      key: 'co_lecturer',
      label: 'Co-lecturer (optional)',
      render: (row) => {
        const draft = draftOf(row);
        return (
          <TeacherPicker
            value={draft.co_lecturer}
            lecturers={lecturers}
            excludeId={draft.lecturer}
            label={`Co-lecturer for ${row.course_code}`}
            placeholder="None"
            onChange={(id) => updateDraft(row, { co_lecturer: id })}
          />
        );
      },
    },
    {
      key: 'departments',
      label: 'Shared with',
      render: (row) => (
        <DepartmentPicker
          value={draftOf(row).departments}
          departments={departments}
          primaryId={row.department}
          label={`Departments for ${row.course_code}`}
          onChange={(ids) => updateDraft(row, { departments: ids })}
        />
      ),
    },
    {
      key: 'actions',
      label: '',
      align: 'right',
      render: (row) => (
        <button
          type="button"
          className="fet-btn-secondary shrink-0"
          onClick={() => save(row)}
          disabled={!isDirty(row) || busyId === row.id}
        >
          {busyId === row.id ? 'Saving...' : 'Save'}
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {error ? <Callout tone="bad">{error}</Callout> : null}
      {notice ? <Callout tone="ok">{notice}</Callout> : null}
      {!loading && !activeSemester ? (
        <Callout tone="wn">
          No semester is active. You can still assign lecturers, but students cannot
          register and lecturers cannot open new classrooms until one is active on the{' '}
          <b>Semesters</b> tab.
        </Callout>
      ) : null}
      <Callout tone="in" icon={UserCheck}>
        Assign each course offering to its lead lecturer and, optionally, a co-lecturer
        (search by name, email or initials). Both get the classroom on their panel and
        can take attendance. Use <b>Shared with</b> so students from other departments
        can also register. Active-semester offerings are listed first.
        {unassigned > 0 ? <span className="block mt-1">{unassigned} offering{unassigned === 1 ? '' : 's'} currently unassigned.</span> : null}
      </Callout>
      <Card accent="hub">
        <CardHead title="Course offerings" square="hub">
          <button type="button" onClick={load} className="fet-btn-secondary text-[12px]">Refresh</button>
        </CardHead>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            empty={loading
              ? <p className="text-text-secondary text-[13px] py-6 text-center">Loading offerings...</p>
              : <EmptyState icon={BookOpen} title="No course offerings yet" subtitle="Create offerings before assigning lecturers." />}
          />
        </CardBody>
      </Card>
    </div>
  );
};

const AcademicSetup = () => {
  const [tab, setTab] = useState('semesters');

  return (
    <div className="space-y-5">
      <SectionHeader
        area="hub"
        icon={Building2}
        title="Academic setup"
        subtitle="Manage active semesters, departments, and lecturer assignments for course offerings."
      />
      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { key: 'semesters', label: 'Semesters', icon: CalendarRange },
          { key: 'departments', label: 'Departments', icon: Building2 },
          { key: 'offerings', label: 'Course lecturers', icon: UserCheck },
        ]}
      />
      {tab === 'semesters' ? <SemesterPanel /> : null}
      {tab === 'departments' ? <DepartmentPanel /> : null}
      {tab === 'offerings' ? <CourseOfferingPanel /> : null}
    </div>
  );
};

export default AcademicSetup;
