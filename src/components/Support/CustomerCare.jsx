import React, { useCallback, useEffect, useState } from 'react';
import api from '../../lib/api';
import { normalizeRole } from '../../lib/profile';

const unwrap = (response) => response.data?.data ?? response.data;

const CustomerCare = ({ user }) => {
  const isAdmin = normalizeRole(user?.role) === 'admin';
  const [mine, setMine] = useState([]);
  const [queue, setQueue] = useState([]);
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [replies, setReplies] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const own = await api.get('/support/contact/');
      setMine(unwrap(own));
      if (isAdmin) {
        const admin = await api.get('/admin/support/');
        setQueue(unwrap(admin));
      }
      setError('');
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not load customer care requests.');
    }
  }, [isAdmin]);

  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post('/support/contact/', { subject, message });
      setSubject('');
      setMessage('');
      await load();
    } catch (err) {
      setError(err.response?.data?.error?.message || err.response?.data?.error || 'Could not send request.');
    } finally {
      setBusy(false);
    }
  };

  const update = async (ticket, changes) => {
    setBusy(true);
    try {
      await api.patch(`/admin/support/${ticket.id}/`, changes);
      setReplies((current) => ({ ...current, [ticket.id]: '' }));
      await load();
    } catch (err) {
      setError(err.response?.data?.error?.message || err.response?.data?.error || 'Could not update request.');
    } finally {
      setBusy(false);
    }
  };

  const renderTicket = (ticket, manage = false) => (
    <article key={ticket.id} className="fet-card p-4 space-y-3">
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <h3 className="font-semibold text-text-primary">{ticket.subject}</h3>
          {manage && <p className="text-xs text-text-secondary">{ticket.actor_name || ticket.actor_email} · {ticket.actor_email}</p>}
        </div>
        <span className="text-xs text-text-secondary">{ticket.status.replace('_', ' ')}</span>
      </div>
      <p className="text-sm text-text-primary whitespace-pre-wrap">{ticket.message}</p>
      <p className="text-xs text-text-secondary">{new Date(ticket.created_at).toLocaleString()}</p>
      {ticket.replies.map((reply) => (
        <div key={reply.id} className="rounded-lg bg-page-bg p-3 text-sm">
          <strong>{reply.author_name || 'Support'}</strong>
          <p className="whitespace-pre-wrap mt-1">{reply.message}</p>
        </div>
      ))}
      {manage && <div className="space-y-2 border-t pt-3">
        <label className="block text-sm">Status
          <select className="fet-input mt-1" value={ticket.status} disabled={busy}
            onChange={(event) => update(ticket, { status: event.target.value })}>
            <option value="OPEN">Open</option>
            <option value="IN_PROGRESS">In progress</option>
            <option value="RESOLVED">Resolved</option>
          </select>
        </label>
        <textarea className="fet-input w-full" rows={3} placeholder="Write a reply"
          value={replies[ticket.id] || ''} onChange={(event) => setReplies((current) => ({ ...current, [ticket.id]: event.target.value }))} />
        <button type="button" className="fet-btn-primary" disabled={busy || !replies[ticket.id]?.trim()}
          onClick={() => update(ticket, { message: replies[ticket.id] })}>Send reply</button>
      </div>}
    </article>
  );

  return <div className="space-y-6 max-w-4xl">
    <h1 className="text-2xl font-bold text-text-primary">Customer care</h1>
    {error && <p role="alert" className="text-danger text-sm">{error}</p>}
    <form onSubmit={submit} className="fet-card p-4 space-y-3">
      <h2 className="font-semibold">New request</h2>
      <input className="fet-input w-full" placeholder="Subject" value={subject} maxLength={200} required
        onChange={(event) => setSubject(event.target.value)} />
      <textarea className="fet-input w-full" placeholder="Describe your issue" value={message} minLength={10} maxLength={10000} rows={4} required
        onChange={(event) => setMessage(event.target.value)} />
      <button className="fet-btn-primary" disabled={busy}>Send request</button>
    </form>
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">My requests</h2>
      {mine.length ? mine.map((ticket) => renderTicket(ticket)) : <p className="text-text-secondary text-sm">No requests yet.</p>}
    </section>
    {isAdmin && <section className="space-y-3">
      <h2 className="text-lg font-semibold">Support queue</h2>
      {queue.length ? queue.map((ticket) => renderTicket(ticket, true)) : <p className="text-text-secondary text-sm">No requests in your scope.</p>}
    </section>}
  </div>;
};

export default CustomerCare;
