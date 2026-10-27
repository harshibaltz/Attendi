import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, RefreshCw, Loader2, Users, ClipboardCheck, Calendar, Clock, Download,
} from 'lucide-react';
import attendanceApi from '../../lib/attendance';
import {
  SectionHeader, Card, CardHead, CardBody, Pill, Tag, Callout, EmptyState,
} from '../UI';
import { formatDateTime } from '../../lib/format';

const STATUS_TONE = {
  ACTIVE: 'ok',
  OPEN: 'ok',
  CLOSED: 'mute',
  EXPIRED: 'wn',
};

const RECORD_TONE = {
  PRESENT: 'ok',
  LATE: 'wn',
  ABSENT: 'bd',
  EXCUSED: 'in',
};

/**
 * The lecturer's detailed register for one attendance session.
 *
 * Everything the list summarised, plus the per-student check-in rows the
 * requirements call for: name, matricule, timestamp, department and level.
 */
const SessionDetail = () => {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await attendanceApi.sessionDetail(sessionId);
      setData(res || null);
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not load this session.');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  const session = data?.session;
  const records = Array.isArray(data?.records) ? data.records : [];

  const exportCsv = () => {
    const head = ['Student Name', 'Matricule', 'Date / Timestamp', 'Department', 'Level', 'Status'];
    const rows = records.map((r) => [
      r.student_name || '',
      r.student_number || '',
      r.recorded_at ? formatDateTime(r.recorded_at) : '',
      r.department || '',
      r.level || '',
      r.status || '',
    ]);
    const csv = [head, ...rows]
      .map((cols) => cols.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${session?.course_code || 'session'}-${session?.class_name || 'attendance'}.csv`.replace(/\s+/g, '-');
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = () => {
    const printWindow = window.open('', '_blank');
    if (!printWindow) return;
    const title = `${session?.course_code || ''} ${session?.course_title || session?.class_name || 'Attendance'} - ${formatDateTime(session?.started_at) || ''}`;
    const rows = records.map((r) => `
      <tr>
        <td>${(r.student_name || '').replace(/</g, '&lt;')}</td>
        <td>${(r.student_number || '').replace(/</g, '&lt;')}</td>
        <td>${r.recorded_at ? formatDateTime(r.recorded_at) : ''}</td>
        <td>${(r.department || '').replace(/</g, '&lt;')}</td>
        <td>${(r.level || '').replace(/</g, '&lt;')}</td>
        <td>${(r.status || '').replace(/</g, '&lt;')}</td>
      </tr>
    `).join('');
    printWindow.document.write(`
      <html>
        <head>
          <title>${title}</title>
          <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            h1 { font-size: 18px; margin-bottom: 10px; }
            h2 { font-size: 14px; margin: 5px 0 20px; color: #666; }
            table { width: 100%; border-collapse: collapse; font-size: 12px; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f5f5f5; }
            tr:nth-child(even) { background-color: #f9f9f9; }
          </style>
        </head>
        <body>
          <h1>${(session?.course_code || '').replace(/</g, '&lt;')} - ${ (session?.course_title || session?.class_name || '').replace(/</g, '&lt;') }</h1>
          <h2>Session: ${formatDateTime(session?.started_at) || ''} | Present: ${session?.present || 0}/${session?.total_eligible || 0} | Mode: ${session?.mode || ''}</h2>
          <table>
            <thead>
              <tr>
                <th>Student Name</th>
                <th>Matricule</th>
                <th>Date / Timestamp</th>
                <th>Department</th>
                <th>Level</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </body>
      </html>
    `);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => { printWindow.print(); printWindow.close(); }, 250);
  };

  return (
    <div className="space-y-5">
      <SectionHeader
        area="attendance"
        icon={ClipboardCheck}
        title={session ? `${session.course_code} · ${session.class_name}` : 'Attendance session'}
        subtitle="Detailed register for this session."
        crumb={[{ label: 'FET Platform' }, { label: 'Attendance', to: '/attendance' }, { label: 'Session' }]}
        actions={(
          <>
            <button type="button" onClick={() => navigate('/attendance')} className="fet-btn-secondary">
              <ArrowLeft size={14} /> Back
            </button>
            <button type="button" onClick={load} className="fet-btn-secondary" disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          </>
        )}
      />

      {error ? <Callout tone="bd">{error}</Callout> : null}

      {loading ? (
        <Card accent="attendance">
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-secondary">
            <Loader2 size={16} className="animate-spin" /> Loading session…
          </div>
        </Card>
      ) : null}

      {!loading && session ? (
        <Card accent="attendance">
          <CardBody>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="flex items-center gap-3">
                <Calendar size={20} className="text-primary" />
                <div>
                  <p className="text-[13px] font-semibold text-text-primary">{formatDateTime(session.started_at)}</p>
                  <p className="text-[11.5px] text-text-secondary">Started</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Clock size={20} className="text-primary" />
                <div>
                  <p className="text-[13px] font-semibold text-text-primary">{formatDateTime(session.expires_at)}</p>
                  <p className="text-[11.5px] text-text-secondary">Window closed</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Users size={20} className="text-primary" />
                <div>
                  <p className="text-[13px] font-semibold text-text-primary">
                    {session.present} / {session.total_eligible}
                  </p>
                  <p className="text-[11.5px] text-text-secondary">Present / eligible</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div>
                  <Pill tone={STATUS_TONE[session.status] || 'mute'} dot>{session.status}</Pill>
                  <p className="mt-1 text-[11.5px] text-text-secondary">{session.mode} mode</p>
                </div>
              </div>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {!loading && session ? (
        <Card accent="attendance">
          <CardHead title={`Checked-in students (${records.length})`}>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={exportCsv}
                className="fet-btn-secondary"
                disabled={records.length === 0}
              >
                <Download size={14} /> Export CSV
              </button>
              <button
                type="button"
                onClick={exportPdf}
                className="fet-btn-secondary"
                disabled={records.length === 0}
              >
                <Download size={14} /> Export PDF
              </button>
            </div>
          </CardHead>
          <CardBody>
            {records.length === 0 ? (
              <EmptyState
                icon={ClipboardCheck}
                title="No check-ins recorded"
                subtitle="Nobody scanned in for this session."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="fet-table">
                  <thead>
                    <tr>
                      <th>Student Name</th>
                      <th>Matricule</th>
                      <th>Date / Timestamp</th>
                      <th>Department</th>
                      <th>Level</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((r) => (
                      <tr key={r.id}>
                        <td className="font-medium text-text-primary">{r.student_name || '—'}</td>
                        <td className="text-text-secondary">{r.student_number || '—'}</td>
                        <td className="text-text-secondary">{r.recorded_at ? formatDateTime(r.recorded_at) : '—'}</td>
                        <td className="text-text-secondary">{r.department || '—'}</td>
                        <td className="text-text-secondary">{r.level || '—'}</td>
                        <td>
                          <Pill tone={RECORD_TONE[r.status] || 'mute'}>{r.status || '—'}</Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
};

export default SessionDetail;
