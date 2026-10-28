import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Plus, X, Trash2, Pin, Loader2, Megaphone, Search, Check } from 'lucide-react';
import AnnouncementForm from './AnnouncementForm';
import { announcementsApi } from '../../lib/announcements';
import { learningApi } from '../../lib/learning';
import { normalizeRole } from '../../lib/profile';
import {
  SectionHeader, Card, Tag, Pill, Avatar, AvatarStack, Callout, EmptyState, Eyebrow,
} from '../UI';

const TONES = ['#3C5F9E', '#1F7355', '#8E5C0C', '#8A4661', '#4A5261'];

const formatDate = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
};

const REVEAL = 96;      // width of the revealed Delete action, in px
const OPEN_AT = -52;    // drag past this (negative = left) to latch open

/**
 * A row that can be dragged left to reveal a destructive action underneath.
 *
 * Pointer events cover mouse, touch and pen. The wrapper only hijacks the
 * gesture once it is clearly horizontal, so vertical page scrolling still
 * works (`touch-action: pan-y`). A tap that never became a drag falls through
 * to the child, so clicking the card still marks it read.
 */
const SwipeRow = ({ children, onDelete, disabled = false, deleting = false }) => {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, y: 0, base: 0, active: false, decided: false, horiz: false });
  const draggedRef = useRef(false);
  const trackRef = useRef(null);

  const onPointerDown = (e) => {
    if (disabled) return;
    start.current = { x: e.clientX, y: e.clientY, base: offset, active: true, decided: false, horiz: false };
  };

  const onPointerMove = (e) => {
    const s = start.current;
    if (!s.active) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (!s.decided) {
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
      s.decided = true;
      s.horiz = Math.abs(dx) > Math.abs(dy);
      if (s.horiz) {
        draggedRef.current = true;
        setDragging(true);
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ }
      } else {
        s.active = false;
        return;
      }
    }
    if (!s.horiz) return;
    // Clamp between fully-open (left) and a little rubber-band past closed.
    let next = s.base + dx;
    if (next > 12) next = 12;
    if (next < -REVEAL - 24) next = -REVEAL - 24;
    setOffset(next);
  };

  const finish = (e) => {
    const s = start.current;
    if (!s.active) return;
    s.active = false;
    if (!s.horiz) return;
    setDragging(false);
    setOffset(offset <= OPEN_AT ? -REVEAL : 0);
    if (e && e.currentTarget && e.currentTarget.releasePointerCapture) {
      try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
    }
  };

  const handleDelete = async () => {
    setOffset(-REVEAL);
    await onDelete();
  };

  useEffect(() => {
    if (offset === 0) return undefined;
    const onDown = (e) => {
      if (trackRef.current && !trackRef.current.contains(e.target)) setOffset(0);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [offset]);

  return (
    <div className="ui-swipe">
      <button
        type="button"
        className="ui-swipe-delete"
        onClick={handleDelete}
        disabled={deleting}
        aria-label="Delete announcement"
        tabIndex={offset < 0 ? 0 : -1}
      >
        {deleting ? <Loader2 size={18} className="animate-spin" /> : <Trash2 size={18} />}
        Delete
      </button>
      <div
        ref={trackRef}
        className={`ui-swipe-track${dragging ? ' is-dragging' : ''}`}
        style={{ transform: `translateX(${offset}px)` }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={finish}
        onPointerLeave={(e) => { if (start.current.active) finish(e); }}
        onClickCapture={(e) => {
          // A drag must not also fire the card's click (which marks it read).
          if (draggedRef.current) {
            draggedRef.current = false;
            e.preventDefault();
            e.stopPropagation();
          }
        }}
      >
        {children}
      </div>
    </div>
  );
};

const AnnouncementList = ({ user }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [query, setQuery] = useState('');
  // Needed so a course-scoped announcement can name a course.
  const [myOfferings, setMyOfferings] = useState([]);
  const role = normalizeRole(user?.role);
  const canPost = role === 'lecturer' || role === 'admin';

  useEffect(() => {
    if (!canPost) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await learningApi.getMyCourses(role);
        if (!cancelled) setMyOfferings(data || []);
      } catch {
        /* the picker just stays empty; faculty scope still works */
      }
    })();
    return () => { cancelled = true; };
  }, [canPost, role]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await announcementsApi.list();
      const list = Array.isArray(data) ? data : [];
      let dismissed = [];
      try { dismissed = JSON.parse(localStorage.getItem('fet_dismissed_announcements') || '[]'); } catch { dismissed = []; }
      setItems(list.filter((a) => !dismissed.includes(a.id)));
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not load announcements.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Opening an announcement is what marks it read, so receipts stay honest.
  const markRead = async (id) => {
    const target = items.find((a) => a.id === id);
    if (!target || target.is_read) return;
    setItems((prev) => prev.map((a) => (a.id === id ? { ...a, is_read: true, read_count: a.read_count + 1 } : a)));
    try {
      await announcementsApi.markRead(id);
    } catch {
      setItems((prev) => prev.map((a) => (a.id === id ? { ...a, is_read: false, read_count: a.read_count - 1 } : a)));
    }
  };

  const markAllRead = async () => {
    const targets = items.filter((a) => !a.is_read);
    if (!targets.length) return;
    setItems((prev) => prev.map((a) => (a.is_read ? a : { ...a, is_read: true, read_count: a.read_count + 1 })));
    await Promise.all(targets.map((a) => announcementsApi.markRead(a.id).catch(() => {
      setItems((prev) => prev.map((x) => (x.id === a.id ? { ...x, is_read: false, read_count: x.read_count - 1 } : x)));
    })));
  };

  const togglePin = async (item) => {
    setBusyId(item.id);
    setError('');
    try {
      await announcementsApi.setPinned(item.id, !item.is_pinned);
      await load();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not change the pin.');
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Remove "${item.title}"?`)) return;
    setBusyId(item.id);
    setError('');
    try {
      await announcementsApi.remove(item.id);
      await load();
    } catch (err) {
      setError(err.response?.data?.error?.message || 'Could not remove the announcement.');
    } finally {
      setBusyId(null);
    }
  };

  // Swipe-to-delete. Managers (author/admin) really delete it for everyone;
  // everyone else can only dismiss it from their own view, so we hide it
  // locally and remember that choice. The backend has no per-user dismiss.
  const dismissBySwipe = async (item) => {
    if (item.can_manage) {
      setBusyId(item.id);
      setError('');
      try {
        await announcementsApi.remove(item.id);
        await load();
      } catch (err) {
        setError(err.response?.data?.error?.message || 'Could not remove the announcement.');
        setBusyId(null);
      }
      return;
    }
    setItems((prev) => prev.filter((a) => a.id !== item.id));
    try {
      const key = 'fet_dismissed_announcements';
      const stored = JSON.parse(localStorage.getItem(key) || '[]');
      if (!stored.includes(item.id)) {
        localStorage.setItem(key, JSON.stringify([...stored, item.id]));
      }
    } catch {
      /* private mode / quota — the in-memory hide is enough for this session */
    }
  };

  const handleSaved = async () => {
    setShowForm(false);
    await load();
  };

  // Search matches the title, the body, or the course/audience tag
  // (e.g. "CEF331"), case-insensitively.
  const q = query.trim().toLowerCase();
  const visible = useMemo(() => {
    if (!q) return items;
    return items.filter((a) => (
      (a.title || '').toLowerCase().includes(q)
      || (a.content || '').toLowerCase().includes(q)
      || (a.audience_label || '').toLowerCase().includes(q)
    ));
  }, [items, q]);

  const pinned = visible.find((a) => a.is_pinned) || null;
  const rest = pinned ? visible.filter((a) => a.id !== pinned.id) : visible;
  const unread = items.filter((a) => !a.is_read).length;

  const Receipt = ({ item }) => {
    const total = item.recipient_count || 0;
    const read = item.read_count || 0;
    const pct = total > 0 ? Math.round((read / total) * 100) : 0;
    const people = (item.readers || []).map((r) => ({ name: r.full_name || r.user_name }));
    return (
      <div className="ui-receipt">
        {people.length ? (
          <AvatarStack people={people} max={4} size={21} tones={TONES} />
        ) : null}
        <span className="tally">{read} of {total} read</span>
        <span className="ui-tally-bar"><i style={{ width: `${pct}%` }} /></span>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <SectionHeader
        area="announcements"
        icon={Megaphone}
        title="Announcements"
        subtitle="Send to one course or to the whole faculty."
        crumb={[{ label: 'FET Platform' }, { label: 'Announcements' }]}
        actions={canPost ? (
          <button type="button" onClick={() => setShowForm(true)} className="fet-btn-primary">
            <Plus size={15} /> New announcement
          </button>
        ) : null}
      />

      {error ? <Callout tone="bd" icon={AlertCircleIcon}>{error}</Callout> : null}

      {/* Search sits directly under the header, above the list. */}
      {!loading && items.length > 0 ? (
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search announcements by title, content, or course (e.g. CEF331)..."
            className="fet-input pl-9"
            aria-label="Search announcements"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-text-muted transition-colors hover:bg-page-bg"
              aria-label="Clear search"
            >
              <X size={15} />
            </button>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <Card accent="announcements">
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-secondary">
            <Loader2 size={16} className="animate-spin" /> Loading announcements...
          </div>
        </Card>
      ) : null}

      {!loading && items.length === 0 ? (
        <Card accent="announcements">
          <EmptyState
            icon={Megaphone}
            title="Nothing has been posted yet"
            subtitle={canPost
              ? 'Post a notice and it appears here for everyone in the audience you pick.'
              : 'Notices for your courses and department will appear here.'}
            action={canPost ? (
              <button type="button" onClick={() => setShowForm(true)} className="fet-btn-primary">
                <Plus size={15} /> New announcement
              </button>
            ) : null}
          />
        </Card>
      ) : null}

      {unread > 0 ? (
        <div className="flex items-center gap-2">
          <Pill tone="in">{unread} unread</Pill>
          <button
            type="button"
            onClick={markAllRead}
            className="text-[12px] font-medium text-primary hover:underline"
          >
            Mark all as read
          </button>
        </div>
      ) : null}

      {!loading && q && visible.length === 0 ? (
        <Card accent="announcements">
          <EmptyState
            icon={Search}
            title="No matching announcements"
            subtitle={`Nothing matches "${query.trim()}". Try a different word or clear the search.`}
            action={(
              <button type="button" onClick={() => setQuery('')} className="fet-btn-secondary">
                Clear search
              </button>
            )}
          />
        </Card>
      ) : null}

      {/* The pinned announcement is the one card that must be seen. */}
      {pinned ? (
        <div className="ui-hero">
          <div className="ui-hero-wash">
            <span className="ui-ribbon"><Pin size={12} /> Pinned</span>
            <button
              type="button"
              onClick={() => markRead(pinned.id)}
              className="mt-3 block w-full text-left"
            >
              <div className="ui-hero-title">{pinned.title}</div>
              <p className="ui-hero-body">{pinned.content}</p>
            </button>
          </div>
          <div className="ui-card-foot">
            <div className="flex min-w-0 items-center gap-2">
              <Avatar name={pinned.creator_name} size={30} tone="#5F2F44" />
              <span className="truncate text-[12.5px] text-text-secondary">
                <b className="text-text-primary">{pinned.creator_name}</b>
                {' '}· {pinned.audience_label}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {pinned.can_manage ? <Receipt item={pinned} /> : null}
              {pinned.can_manage ? (
                <>
                  <button
                    type="button"
                    onClick={() => togglePin(pinned)}
                    disabled={busyId === pinned.id}
                    className="fet-btn-secondary"
                    style={{ padding: '6px 11px', fontSize: 12.5 }}
                  >
                    {busyId === pinned.id ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />} Unpin
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(pinned)}
                    disabled={busyId === pinned.id}
                    className="fet-btn-danger"
                    style={{ padding: '6px 11px', fontSize: 12.5 }}
                  >
                    <Trash2 size={14} /> Remove
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="space-y-4">
        {rest.map((item) => {
          const expired = item.is_expired;
          return (
            <SwipeRow
              key={item.id}
              onDelete={() => dismissBySwipe(item)}
              deleting={busyId === item.id}
            >
              <div className={`ui-ann ${item.is_read ? 'ui-ann-read' : 'ui-ann-unread'}`}>
                <div className="ui-ann-top">
                  <Avatar name={item.creator_name} size={34} tone={item.is_read ? '#4A5261' : '#8A4661'} />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="ui-ann-title">{item.title}</span>
                      {!item.is_read ? <Pill tone="in">New</Pill> : null}
                      {item.is_pinned ? <Pill tone="wn">Pinned</Pill> : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Tag>{item.audience_label}</Tag>
                      <span className="text-[11.5px] text-text-muted">{formatDate(item.published_at)}</span>
                      {expired ? <Pill tone="wn" dot>Expired</Pill> : null}
                    </div>
                  </div>
                  {item.can_manage ? (
                    <div className="flex shrink-0 items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => togglePin(item)}
                        disabled={busyId === item.id}
                        className="fet-btn-secondary"
                        style={{ padding: '6px 10px' }}
                        title={item.is_pinned ? 'Unpin' : 'Pin to the top'}
                        aria-label={item.is_pinned ? `Unpin ${item.title}` : `Pin ${item.title}`}
                      >
                        <Pin size={15} />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(item)}
                        disabled={busyId === item.id}
                        className="fet-btn-danger"
                        style={{ padding: '6px 10px' }}
                        aria-label={`Remove ${item.title}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={() => markRead(item.id)}
                  className="block w-full text-left"
                  aria-label={item.is_read ? undefined : `Mark ${item.title} as read`}
                >
                  <p className="ui-ann-body">{item.content}</p>
                </button>

                <div className="ui-ann-foot">
                  <span className="text-[11.5px] text-text-muted">
                    Posted by {item.creator_name}
                  </span>
                  <div className="flex-1" />
                  {!item.is_read ? (
                    <button
                      type="button"
                      onClick={() => markRead(item.id)}
                      className="inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline"
                    >
                      <Check size={13} /> Mark as read
                    </button>
                  ) : null}
                  {item.can_manage ? <Receipt item={item} /> : null}
                </div>
              </div>
            </SwipeRow>
          );
        })}
      </div>

      {showForm ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-surface shadow-modal">
            <div className="flex items-center justify-between border-b border-border-default p-5">
              <h3 className="text-[15px] font-bold text-text-primary">New announcement</h3>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded-md p-1.5 transition-colors hover:bg-page-bg"
                aria-label="Close"
              >
                <X size={20} className="text-text-secondary" />
              </button>
            </div>
            <div className="p-5">
              <AnnouncementForm
                courses={myOfferings}
                onCancel={() => setShowForm(false)}
                onSaved={handleSaved}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

/* Small local icon so the error callout matches the rest of the app. */
function AlertCircleIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

export default AnnouncementList;
