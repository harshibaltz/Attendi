import React, { useEffect, useMemo, useState } from 'react';
import { Users as UsersIcon, Search, UserCheck, UserX } from 'lucide-react';
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

const Users = ({ user: currentUser }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('ALL');

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
    acc[row.status] = (acc[row.status] || 0) + 1;
    return acc;
  }, {}), [rows]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (roleFilter !== 'ALL' && row.role !== roleFilter) return false;
      if (!needle) return true;
      return `${row.full_name || ''} ${row.email || ''}`.toLowerCase().includes(needle);
    });
  }, [rows, query, roleFilter]);

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
        subtitle="Every account on the platform. Restoration brings back a self-deleted account without touching its academic records."
        actions={(
          <>
            <Pill tone="ok" dot>{counts.ACTIVE || 0} active</Pill>
            <Pill tone="wn" dot>{counts.SUSPENDED || 0} suspended</Pill>
            <Pill tone="bd" dot>{counts.ARCHIVED || 0} archived</Pill>
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
                placeholder="Search by name or email"
                className="fet-input pl-10 w-full"
                aria-label="Search accounts"
              />
            </div>
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="fet-select sm:w-56"
              aria-label="Filter by role"
            >
              <option value="ALL">All roles</option>
              {Object.entries(ROLE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </CardBody>
      </Card>

      <Callout tone="wn">
        Deactivating blocks sign-in immediately and revokes the account&apos;s sessions.
        Records stay intact — restore the account any time.
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
                      <div className="text-[12px] text-text-secondary truncate">{row.email}</div>
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
                    <Pill tone={STATUS_TONES[row.status] || 'mu'} dot>
                      {STATUS_LABELS[row.status] || row.status}
                    </Pill>
                  ),
                },
                {
                  key: 'actions',
                  label: '',
                  align: 'right',
                  width: '130px',
                  render: (row) => {
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
    </div>
  );
};

export default Users;
