import React, { useState, useEffect, useCallback } from 'react';
import { Building2, CalendarRange, Plus, Check, X, BookOpen, UserCheck } from 'lucide-react';
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

const CourseOfferingPanel = () => {
  const [rows, setRows] = useState([]);
  const [lecturers, setLecturers] = useState([]);
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
      const [offerings, lecturerRows, semesterRows] = await Promise.all([
        academicsApi.courseOfferings(),
        academicsApi.lecturers(),
        academicsApi.semesters(),
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
      setDrafts(Object.fromEntries(offeringRows.map((row) => [row.id, row.lecturer || ''])));
    } catch (err) {
      setError(errorMessage(err, 'Could not load course offerings and lecturers.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (row) => {
    const lecturerId = drafts[row.id] || null;
    setBusyId(row.id);
    setError('');
    setNotice('');
    try {
      await academicsApi.assignLecturer(row.id, lecturerId);
      const lecturer = lecturers.find((item) => item.id === lecturerId);
      setNotice(
        `${row.course_code} assigned to ${lecturer?.full_name || 'no lecturer'}. ` +
        (lecturer ? 'The classroom is now on their panel, ready for attendance.' : ''),
      );
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
    { key: 'department_name', label: 'Department' },
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
      label: 'Teaching lecturer',
      render: (row) => {
        const draft = drafts[row.id] ?? row.lecturer ?? '';
        const changed = draft !== (row.lecturer || '');
        return (
          <div className="flex min-w-[260px] flex-col gap-1">
            <div className="flex items-center gap-2">
              <select
                aria-label={`Lecturer for ${row.course_code}`}
                className="fet-input min-w-0 flex-1"
                value={draft}
                onChange={(event) => setDrafts((current) => ({ ...current, [row.id]: event.target.value }))}
              >
                <option value="">Unassigned</option>
                {lecturers.map((lecturer) => (
                  <option key={lecturer.id} value={lecturer.id}>
                    {lecturer.full_name} · {lecturer.email}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="fet-btn-secondary shrink-0"
                onClick={() => save(row)}
                disabled={!changed || busyId === row.id}
              >
                {busyId === row.id ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        );
      },
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
        Assign each course offering to its actual teaching lecturer. The lecturer
        immediately gets that classroom on their panel and can take attendance for it.
        Active-semester offerings are listed first.
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
