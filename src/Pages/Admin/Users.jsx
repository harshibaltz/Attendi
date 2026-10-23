import React, { useEffect, useMemo, useState } from 'react';
import { Users as UsersIcon, Search, UserCheck, UserX, Eye, X } from 'lucide-react';
import { SectionHeader, Card, CardBody, CardHead, Callout, DataTable, EmptyState, Pill } from '../../components/UI';
import { usersApi } from '../../lib/users';
import { errorMessage } from '../../lib/enrollment';

const ROLE_LABELS = {
  STUDENT: 'Student',
  LECTURER: 'Lecturer',
  DEPARTMENT_ADMIN: 'Department admin',
  FACULTY_ADMIN: 'Faculty admin',
  SYSTEM_ADMIN: 'System admin',
};

const STATUS_LABELS = { ACTIVE: 'Active', SUSPENDED: 'Suspended', ARCHIVED: 'Archived' };
const STATUS_TONES = { ACTIVE: 'ok', SUSPENDED: 'wn', ARCHIVED: 'bd' };
const DELETE_REASON_LABELS = {
  NO_LONGER_NEEDED: 'No longer needed',
  GRADUATED: 'Graduated or left the university',
  PRIVACY: 'Privacy concerns',
  TOO_MANY_ISSUES: 'Problems or bugs with the platform',
  SWITCHING_ACCOUNT: 'Wants to create a new account',
  OTHER: 'Other',
};

const formatDateTime = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

const Users = ({ user: currentUser }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('ALL');
  const [stateFilter, setStateFilter] = useState('ALL');
  const [selectedDeleted, setSelectedDeleted] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await usersApi.list();
        if (!cancelled) setRows(Array.isArray(list) ? list : []);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, 'Could not load accounts.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const counts = useMemo(() => rows.reduce((acc, row) => {
    const state = row.deleted_at ? 'DELETED' : row.status;
    acc[state] = (acc[state] || 0) + 1;
    return acc;
  }, {}), [rows]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (roleFilter !== 'ALL' && row.role !== roleFilter) return false;
      const state = row.deleted_at ? 'DELETED' : row.status;
      if (stateFilter !== 'ALL' && state !== stateFilter) return false;
      if (!needle) return true;
      const haystack = [
        row.full_name,
        row.email,
        row.deleted_from_email,
        row.student_number,
        row.deleted_from_student_number,
        row.staff_number,
        row.deleted_from_staff_number,
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(needle);
    });
  }, [rows, query, roleFilter, stateFilter]);

  const changeStatus = async (row, status) => {
    if (status !== 'ACTIVE') {
      const name = row.full_name || row.email;
      if (!window.confirm(`Deactivate ${name}? Their sessions are revoked and they cannot sign in until you restore the account. Grades, attendance and submissions are preserved.`)) return;
    }
    setBusyId(row.id);
    setError('');
    try {
      await usersApi.setStatus(row.id, status);
      setRows((list) => list.map((u) => (u.id === row.id
        ? { ...u, status, is_active: status === 'ACTIVE' }
        : u)));
    } catch (err) {
      setError(errorMessage(err, 'Could not update this account.'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-5">
      <SectionHeader
        area="hub"
        icon={UsersIcon}
        title="Users"
        subtitle="Every account on the platform. Self-deleted accounts stay here with their original identifiers, feedback and academic records."
        actions={(
          <>
            <Pill tone="ok" dot>{counts.ACTIVE || 0} active</Pill>
            <Pill tone="wn" dot>{counts.SUSPENDED || 0} suspended</Pill>
            <Pill tone="bd" dot>{counts.ARCHIVED || 0} archived</Pill>
            <Pill tone="wn" dot>{counts.DELETED || 0} deleted</Pill>
          </>
        )}
      />

      {error ? <Callout tone="bad">{error}</Callout> : null}

      <Card accent="hub">
        <CardBody>
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
            <div className="relative flex-1 min-w-0">
              <Search
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, email or matricule"
                className="fet-input pl-10 w-full"
                aria-label="Search accounts"
              />
            </div>
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="fet-select sm:w-52"
              aria-label="Filter by role"
            >
              <option value="ALL">All roles</option>
              {Object.entries(ROLE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="fet-select sm:w-48"
              aria-label="Filter by account state"
            >
              <option value="ALL">All states</option>
              <option value="ACTIVE">Active</option>
              <option value="SUSPENDED">Suspended</option>
              <option value="ARCHIVED">Archived by admin</option>
              <option value="DELETED">Deleted by owner</option>
            </select>
          </div>
        </CardBody>
      </Card>

      <Callout tone="wn">
        Deactivating blocks sign-in immediately and revokes the account&apos;s sessions;
        you can restore that account later. A self-deleted account cannot be restored
        because its email and matricule were released for re-registration — use
        <strong> View data </strong> to see its archived details and feedback.
      </Callout>

      <Card accent="hub">
        <CardHead title="Accounts" square="hub">
          <Pill tone="mu">{visible.length} shown</Pill>
        </CardHead>
        <CardBody>
          {loading ? (
            <p className="text-[13px] text-text-secondary">Loading accounts...</p>
          ) : (
            <DataTable
              rows={visible}
              empty={(
                <EmptyState
                  icon={UsersIcon}
                  title="No accounts match"
                  subtitle="Try a different search or role filter."
                />
              )}
              columns={[
                {
                  key: 'full_name',
                  label: 'Account',
                  render: (row) => (
                    <div className="min-w-0">
                      <div className="font-medium text-text-primary truncate">{row.full_name || '—'}</div>
                      <div className="text-[12px] text-text-secondary truncate">
                        {row.deleted_at ? (row.deleted_from_email || row.email) : row.email}
                      </div>
                      {row.deleted_at ? (
                        <div className="mt-0.5 text-[11px] font-medium text-danger">Deleted by owner — data archived</div>
                      ) : null}
                    </div>
                  ),
                },
                {
                  key: 'role',
                  label: 'Role',
                  width: '150px',
                  render: (row) => ROLE_LABELS[row.role] || row.role,
                },
                {
                  key: 'status',
                  label: 'Status',
                  width: '120px',
                  render: (row) => (
                    <Pill tone={row.deleted_at ? 'wn' : (STATUS_TONES[row.status] || 'mu')} dot>
                      {row.deleted_at ? 'Deleted' : (STATUS_LABELS[row.status] || row.status)}
                    </Pill>
                  ),
                },
                {
                  key: 'actions',
                  label: '',
                  align: 'right',
                  width: '130px',
                  render: (row) => {
                    if (row.deleted_at) {
                      return (
                        <button
                          type="button"
                          onClick={() => setSelectedDeleted(row)}
                          className="fet-btn-secondary text-[12px]"
                        >
                          <Eye size={13} /> View data
                        </button>
                      );
                    }
                    const isSelf = row.id === currentUser?.id;
                    if (row.status === 'ACTIVE') {
                      return (
                        <button
                          type="button"
                          onClick={() => changeStatus(row, 'SUSPENDED')}
                          disabled={isSelf || busyId === row.id}
                          title={isSelf ? 'You cannot deactivate your own account.' : undefined}
                          className="fet-btn-secondary text-[12px]"
                        >
                          <UserX size={13} /> {busyId === row.id ? 'Working...' : 'Deactivate'}
                        </button>
                      );
                    }
                    return (
                      <button
                        type="button"
                        onClick={() => changeStatus(row, 'ACTIVE')}
                        disabled={busyId === row.id}
                        className="fet-btn-primary text-[12px]"
                      >
                        <UserCheck size={13} /> {busyId === row.id
                          ? 'Working...'
                          : (row.status === 'ARCHIVED' ? 'Restore' : 'Activate')}
                      </button>
                    );
                  },
                },
              ]}
            />
          )}
        </CardBody>
      </Card>

      {selectedDeleted && (
        <div
          className="fixed inset-0 z-[95] grid place-items-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          onClick={() => setSelectedDeleted(null)}
        >
          <div
            className="max-h-[85dvh] w-full max-w-lg overflow-y-auto rounded-xl bg-surface p-5 shadow-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h4 className="text-[15px] font-bold text-text-primary">Deleted account data</h4>
                <p className="mt-1 text-[12px] text-text-secondary">
                  Archived for administrators. The person can register again with the original
                  email and matricule, but this login cannot be restored.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDeleted(null)}
                className="rounded-lg p-1.5 text-text-secondary hover:bg-page-bg"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Name</dt>
                <dd className="text-[13px] font-medium text-text-primary">{selectedDeleted.full_name || '—'}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Role</dt>
                <dd className="text-[13px] text-text-primary">{ROLE_LABELS[selectedDeleted.role] || selectedDeleted.role}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Original email</dt>
                <dd className="text-[13px] text-text-primary break-all">{selectedDeleted.deleted_from_email || '—'}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Personal email</dt>
                <dd className="text-[13px] text-text-primary break-all">{selectedDeleted.deleted_from_personal_email || '—'}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Matricule / staff no.</dt>
                <dd className="text-[13px] text-text-primary">
                  {selectedDeleted.deleted_from_student_number
                    || selectedDeleted.deleted_from_staff_number
                    || '—'}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Deleted at</dt>
                <dd className="text-[13px] text-text-primary">{formatDateTime(selectedDeleted.deleted_at)}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Reason</dt>
                <dd className="text-[13px] text-text-primary">
                  {DELETE_REASON_LABELS[selectedDeleted.deletion_reason] || selectedDeleted.deletion_reason || '—'}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">What could we improve?</dt>
                <dd className="whitespace-pre-wrap text-[13px] text-text-primary">
                  {selectedDeleted.deletion_improvement || 'No comment provided.'}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary">Account ID</dt>
                <dd className="text-[12px] text-text-secondary break-all">{selectedDeleted.id}</dd>
              </div>
            </dl>

            <div className="mt-5 flex justify-end">
              <button type="button" onClick={() => setSelectedDeleted(null)} className="fet-btn-secondary">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Users;
