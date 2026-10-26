import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, Bell, ChevronDown, User, LogOut, Settings, CheckCheck, Moon, Sun,
} from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { normalizeRole } from '../../lib/profile';
import { notificationsApi } from '../../lib/notifications';
import { relativeTime } from '../../lib/format';

const TYPE_TONE = {
  ATTENDANCE: 'Attendance',
  ASSESSMENT: 'Assessment',
  GRADE: 'Grade',
  ANNOUNCEMENT: 'Announcement',
  ENROLLMENT: 'Enrollment',
  CARRY_OVER: 'Carry-over',
  PLATFORM_UPDATE: 'Platform Update',
};

const Header = ({ user, onLogout }) => {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const notifRef = useRef(null);
  const profileRef = useRef(null);

  // The bell reads the real, unread-only feed. That keeps it honest with the
  // sidebar badge and the Notifications page, which share the same endpoint.
  const loadNotifications = useCallback(async () => {
    try {
      const list = await notificationsApi.list(true);
      setNotifications(Array.isArray(list) ? list : []);
    } catch {
      /* a failed fetch must not break the header */
    }
  }, []);

  useEffect(() => { loadNotifications(); }, [loadNotifications]);

  useEffect(() => {
    const onChanged = () => loadNotifications();
    window.addEventListener('fet-notifications-changed', onChanged);
    return () => window.removeEventListener('fet-notifications-changed', onChanged);
  }, [loadNotifications]);

  useEffect(() => {
    const handleClick = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) setShowNotifications(false);
      if (profileRef.current && !profileRef.current.contains(e.target)) setShowProfile(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const name = user?.fullName || 'User';
  const role = normalizeRole(user?.role || 'student');
  const initials = name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);
  const unreadCount = notifications.length;

  // Any read action drops the row from this unread-only list and tells the
  // sidebar to refresh its badge.
  const markAsRead = async (id) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    try {
      await notificationsApi.markRead(id);
      window.dispatchEvent(new Event('fet-notifications-changed'));
    } catch {
      loadNotifications();
    }
  };
  const markAllAsRead = async () => {
    setNotifications([]);
    try {
      await notificationsApi.markAllRead();
      window.dispatchEvent(new Event('fet-notifications-changed'));
    } catch {
      loadNotifications();
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('fet_auth');
    localStorage.removeItem('fet_user');
    localStorage.removeItem('fet_user_role');
    localStorage.removeItem('fet_user_name');
    if (onLogout) onLogout();
    else window.location.reload();
  };

  // On phones the panel is pinned to the viewport (fixed, inset-x) so it can
  // never overflow the screen edge; from sm up it hangs off the bell as usual.
  const panel = 'fixed inset-x-3 top-[66px] z-[90] w-auto sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-80 bg-surface rounded-lg shadow-modal border border-border-default overflow-hidden max-h-[calc(100dvh-80px)] flex flex-col';
  const menuItem = 'w-full flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-text-primary hover:bg-page-bg transition-colors text-left';

  return (
    <header className="relative z-40 flex h-[58px] shrink-0 items-center gap-3 border-b border-border-default bg-surface px-4 md:px-6">
      {/* Search is shown only when the sidebar is pinned (lg+). Below that the
          hamburger sits in the header's left area, so the field would collide
          with it — and the flex-1 spacer keeps that corner clear. */}
      <div className="relative hidden lg:block max-w-[430px] flex-1">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          type="text"
          placeholder="Search classrooms, projects, students"
          className="fet-input pl-[34px] pr-16 text-[13px]"
          style={{ backgroundColor: 'rgb(var(--canvas))' }}
        />
        <span
          className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 items-center rounded-[4px] border border-border-default bg-surface px-1.5 text-[10px] text-text-secondary lg:flex"
          style={{ height: 19, borderBottomWidth: 2 }}
        >
          Ctrl K
        </span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-1.5 md:gap-2">
        <button
          type="button"
          onClick={toggleTheme}
          className="grid h-9 w-9 place-items-center rounded-md border border-border-default bg-surface text-text-secondary transition-colors hover:bg-page-bg"
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        <div className="relative" ref={notifRef}>
          <button
            type="button"
            onClick={() => { setShowNotifications((v) => !v); setShowProfile(false); }}
            className="relative grid h-9 w-9 place-items-center rounded-md border border-border-default bg-surface text-text-secondary transition-colors hover:bg-page-bg"
            aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
          >
            <Bell size={16} />
            {unreadCount > 0 ? (
              <span className="absolute -right-1 -top-1 grid h-[17px] min-w-[17px] place-items-center rounded-full bg-danger px-[4px] text-[10px] font-semibold leading-none text-white ring-2 ring-surface">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            ) : null}
          </button>

          {showNotifications ? (
            <div className={panel}>
              <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
                <p className="text-[13px] font-semibold text-text-primary">
                  Notifications
                  {unreadCount > 0 ? <span className="ml-1.5 text-text-secondary">({unreadCount})</span> : null}
                </p>
                {unreadCount > 0 ? (
                  <button
                    type="button"
                    onClick={markAllAsRead}
                    className="flex items-center gap-1 text-[12px] font-medium text-primary hover:opacity-80"
                  >
                    <CheckCheck size={14} /> Mark all read
                  </button>
                ) : null}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                {notifications.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                    <Bell size={22} className="text-text-muted" />
                    <p className="text-[13px] font-medium text-text-primary">No unread notifications</p>
                    <button
                      type="button"
                      onClick={() => { setShowNotifications(false); navigate('/notifications'); }}
                      className="text-[12px] font-medium text-primary hover:underline"
                    >
                      View notification history
                    </button>
                  </div>
                ) : notifications.map((n) => (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => markAsRead(n.id)}
                    className="w-full border-b border-border-default/50 bg-primary-light/40 px-4 py-3 text-left transition-colors last:border-0 hover:bg-page-bg"
                  >
                    <span className="text-[10px] font-bold uppercase tracking-wider text-primary">
                      {TYPE_TONE[n.type] || n.type || 'Notice'}
                    </span>
                    <p className="mt-0.5 text-[13px] font-medium text-text-primary">{n.title}</p>
                    {n.message ? (
                      <p className="mt-0.5 line-clamp-2 text-[12px] text-text-secondary">{n.message}</p>
                    ) : null}
                    <p className="mt-0.5 text-[11px] text-text-secondary">{relativeTime(n.created_at)}</p>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => { setShowNotifications(false); navigate('/notifications'); }}
                className="w-full border-t border-border-default px-4 py-2.5 text-center text-[12px] font-medium text-primary transition-colors hover:bg-page-bg"
              >
                View all notifications
              </button>
            </div>
          ) : null}
        </div>

        <div className="relative" ref={profileRef}>
          <button
            type="button"
            onClick={() => { setShowProfile((v) => !v); setShowNotifications(false); }}
            className="flex items-center gap-2.5 rounded-md py-1 pl-1 pr-2 transition-colors hover:bg-page-bg"
            aria-label="Profile menu"
          >
            <span className="ui-avatar h-8 w-8 bg-primary text-[12px]">{initials}</span>
            <span className="hidden text-left sm:block">
              <span className="block max-w-[110px] truncate text-[13px] font-medium leading-tight text-text-primary">{name}</span>
              <span className="block text-[11px] capitalize leading-tight text-text-secondary">{role}</span>
            </span>
            <ChevronDown size={14} className="hidden text-text-secondary sm:block" />
          </button>

          {showProfile ? (
            <div className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-lg border border-border-default bg-surface shadow-modal">
              <div className="border-b border-border-default px-4 py-3">
                <p className="text-[13px] font-semibold text-text-primary">{name}</p>
                <p className="text-[11px] capitalize text-text-secondary">{role}</p>
              </div>
              <div className="py-1">
                <button type="button" className={menuItem} onClick={() => { setShowProfile(false); navigate('/profile'); }}>
                  <User size={15} /> Profile
                </button>
                <button type="button" className={menuItem} onClick={() => { setShowProfile(false); navigate('/settings'); }}>
                  <Settings size={15} /> Settings
                </button>
                <div className="mx-3 my-1 h-px bg-border-default" />
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-[13px] text-danger transition-colors hover:bg-red-50"
                >
                  <LogOut size={15} /> Sign out
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
};

export default Header;
