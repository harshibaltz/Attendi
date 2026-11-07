import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BookPlus, CalendarClock, Check, Info, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { SectionHeader, Card, CardBody, CardHead, CardFoot, Pill, Callout, EmptyState, Eyebrow } from '../../components/UI';
import { enrollmentApi, errorMessage } from '../../lib/enrollment';
import { formatDate } from '../../lib/format';

const RegistrationPage = () => {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [blocked, setBlocked] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [levelFilter, setLevelFilter] = useState('ALL');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    setBlocked(null);
    try {
      setData(await enrollmentApi.availableCourses());
    } catch (err) {
      // These three are setup problems, not transient failures: the user cannot
      // fix them, so say what is missing instead of offering a retry.
      const code = err?.response?.data?.error?.code;
      if (code === 'NO_ACTIVE_SEMESTER' || code === 'INCOMPLETE_PROFILE') {
        setBlocked({
          code,
          message: err.response.data.error.message,
        });
      } else {
        setError(errorMessage(err, 'Could not load the course list.'));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = (id) => {
    setNotice('');
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const register = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await enrollmentApi.register(selected);
      const partial = res?.errors?.length
        ? ` ${res.errors.length} could not be registered.`
        : '';
      setNotice(`Registered for ${res?.registered_count ?? 0} course(s).${partial}`);
      setSelected([]);
      await load();
    } catch (err) {
      setError(errorMessage(err, 'Registration failed.'));
    } finally {
      setBusy(false);
    }
  };

  const courses = data?.courses || [];
  const eligible = courses.filter((c) => !c.is_enrolled);
  const done = courses.filter((c) => c.is_enrolled);
  const term = query.trim().toLowerCase();
  const levels = useMemo(() => (
    [...new Set(courses.map((c) => c.course_level).filter(Boolean))]
      .sort((a, b) => (Number(b) || 0) - (Number(a) || 0) || String(a).localeCompare(String(b)))
  ), [courses]);
  const matchesLevel = (c) => levelFilter === 'ALL' || c.course_level === levelFilter;
  const visibleEligible = eligible.filter((c) => (
    matchesLevel(c)
    && (!term || (
      (c.course_code || '').toLowerCase().includes(term)
      || (c.course_title || '').toLowerCase().includes(term)
    ))
  ));
  const visibleDone = done.filter(matchesLevel);
  const totalUnits = courses.reduce((sum, c) => sum + (c.credit_units || 0), 0);
  const pickedUnits = courses
    .filter((c) => selected.includes(c.offering_id))
    .reduce((sum, c) => sum + (c.credit_units || 0), 0);

  return (
    <div className="space-y-5">
      <SectionHeader
        area="classrooms"
        icon={BookPlus}
        title="Course registration"
        subtitle="Pick courses for this semester. Offerings for your department and level are listed, plus lower-level courses you are eligible to take."
        actions={(
          <button type="button" onClick={() => navigate('/lessons')} className="fet-btn-secondary">
            My courses
          </button>
        )}
      />

      {error ? <Callout tone="bad">{error}</Callout> : null}
      {notice ? <Callout tone="ok">{notice}</Callout> : null}

      {blocked ? (
        <Callout tone="warn" icon={Info}>
          {blocked.message}
          {blocked.code === 'NO_ACTIVE_SEMESTER' ? (
            <span className="block mt-1 text-[12px] opacity-80">
              An administrator needs to activate a semester before registration opens.
            </span>
          ) : (
            <span className="block mt-1 text-[12px] opacity-80">
              Add your department and level on the profile page, then come back.
            </span>
          )}
        </Callout>
      ) : null}

      {data ? (
        <Card accent="classrooms">
          <CardHead title={data.semester || 'Current semester'} square="classrooms">
            <Pill tone="mute">{data.level}</Pill>
            <Pill tone="mute">{data.department}</Pill>
          </CardHead>
          <CardBody>
            {data.registration_closed ? (
              <Callout tone="warn" className="mb-4">
                Registration is closed for this semester. Courses with a later
                per-course deadline are still marked open below.
              </Callout>
            ) : data.registration_deadline ? (
              <div className="flex items-center gap-2 text-[12.5px] text-text-secondary mb-4">
                <CalendarClock size={14} />
                Registration closes {formatDate(data.registration_deadline)}
              </div>
            ) : (
              <Callout tone="warn" className="mb-4">
                No registration deadline is set for this semester.
              </Callout>
            )}

            {eligible.length > 0 ? (
              <div className="flex flex-col sm:flex-row gap-2 mb-4">
                <div className="relative flex-1 sm:max-w-[340px]">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search course code or title"
                    aria-label="Search available courses"
                    className="fet-input pl-9"
                  />
                </div>
                <select
                  value={levelFilter}
                  onChange={(e) => setLevelFilter(e.target.value)}
                  className="fet-select sm:w-44"
                  aria-label="Filter by course level"
                >
                  <option value="ALL">All levels</option>
                  {levels.map((level) => (
                    <option key={level} value={level}>Level {level}</option>
                  ))}
                </select>
              </div>
            ) : null}

            {loading ? (
              <p className="text-text-secondary text-[13px] py-6 text-center">Loading courses...</p>
            ) : eligible.length === 0 && done.length === 0 ? (
              <EmptyState
                icon={BookPlus}
                title="No courses available"
                subtitle="There are no active offerings for your department and level this semester."
              />
            ) : (
              <ul className="space-y-2">
                {visibleEligible.map((c) => {
                  const on = selected.includes(c.offering_id);
                  const closed = Boolean(c.registration_closed);
                  return (
                    <li key={c.offering_id}>
                      <label
                        className={`ui-li flex items-center gap-3 ${closed ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
                        style={on ? { borderColor: 'rgb(var(--primary))' } : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={closed}
                          onChange={() => toggle(c.offering_id)}
                          className="w-4 h-4 accent-[rgb(var(--primary))]"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="ui-card-title text-[13px]">
                            <span className="num text-text-secondary">{c.course_code}</span> {c.course_title}
                          </p>
                          <p className="text-[12px] text-text-tertiary mt-0.5">
                            {c.credit_units} units • {c.lecturer_name || 'TBA'}
                            {c.course_level ? ` • Level ${c.course_level}` : ''}
                            {c.registration_deadline
                              ? ` • Closes ${formatDate(c.registration_deadline)}`
                              : ''}
                          </p>
                        </div>
                        {closed ? (
                          <Pill tone="mute">Closed</Pill>
                        ) : on ? (
                          <Pill tone="in" icon={Check}>Selected</Pill>
                        ) : null}
                      </label>
                    </li>
                  );
                })}

                {(term || levelFilter !== 'ALL') && visibleEligible.length === 0 ? (
                  <li className="py-4 text-center text-[13px] text-text-secondary">
                    No course matches those filters.
                  </li>
                ) : null}

                {visibleDone.length > 0 ? (
                  <li className="pt-3 mt-3 border-t border-border-default">
                    <Eyebrow>Already registered</Eyebrow>
                    <ul className="space-y-1.5">
                      {visibleDone.map((c) => (
                        <li key={c.offering_id} className="flex items-center gap-2 text-[13px] text-text-secondary">
                          <Pill tone="ok" icon={Check}>Registered</Pill>
                          <span className="num">{c.course_code}</span> {c.course_title}
                        </li>
                      ))}
                    </ul>
                  </li>
                ) : null}
              </ul>
            )}
          </CardBody>
          {eligible.length > 0 ? (
            <CardFoot>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="text-[12.5px] text-text-secondary">
                  {selected.length} selected • {pickedUnits} of {totalUnits} units
                </div>
                <button
                  type="button"
                  onClick={register}
                  disabled={busy || selected.length === 0}
                  className="fet-btn-primary"
                >
                  {busy ? 'Registering...' : `Register for ${selected.length || ''} course(s)`}
                </button>
              </div>
            </CardFoot>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
};

export default RegistrationPage;
