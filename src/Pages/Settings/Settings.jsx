import React, { useEffect, useMemo, useState } from 'react';
import {
  Settings as SettingsIcon,
  MessageCircle,
  UserPlus,
  RefreshCw,
  Copy,
  Check,
  Send,
  Link2,
  Info,
  Globe,
} from 'lucide-react';
import { SectionHeader, Card, CardBody, CardHead, Callout, Pill } from '../../components/UI';
import api from '../../lib/api';
import { APP_BUILD } from '../../lib/appBuild';
import { getLang, setLang, t } from '../../lib/i18n';

const shareOrCopy = async (text) => {
  try {
    if (navigator.share) {
      await navigator.share({ title: 'Join FET Platform', url: text });
      return true;
    }
  } catch {
    /* ignore */
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

const Settings = ({ user }) => {
  const [active, setActive] = useState('care');
  const [message, setMessage] = useState('');
  const [subject, setSubject] = useState('general');
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [careError, setCareError] = useState('');

  const [language, setLanguageState] = useState(() => getLang());
  const [referral, setReferral] = useState(null);
  const [inviteAvailable, setInviteAvailable] = useState(false);
  const [copied, setCopied] = useState(false);
  const [refError, setRefError] = useState('');

  const [checking, setChecking] = useState(false);
  const [updateMsg, setUpdateMsg] = useState('');
  const [updateOk, setUpdateOk] = useState(false);

  const currentUser = user || (() => {
    try {
      return JSON.parse(localStorage.getItem('fet_user') || 'null');
    } catch {
      return null;
    }
  })();

  const inviteUrl = useMemo(() => {
    if (referral?.code) {
      return `${window.location.origin}/register?ref=${referral.code}`;
    }
    if (currentUser?.id) {
      return `${window.location.origin}/register?ref=${currentUser.id}`;
    }
    return `${window.location.origin}/register`;
  }, [referral, currentUser]);

  // The invite tab is only real when the backend exposes /referrals/me/.
  // Probing it means the tab appears automatically once that API ships,
  // instead of requiring another frontend release to unhide it.
  const loadReferral = async () => {
    setRefError('');
    try {
      const res = await api.get('/referrals/me/');
      const data = res.data?.data ?? res.data;
      setReferral(data);
      setInviteAvailable(true);
    } catch (err) {
      if (err.response?.status === 404) {
        setInviteAvailable(false);
        setRefError('');
      } else {
        setInviteAvailable(true);
        setRefError(err.response?.data?.error?.message || 'Could not load invite link.');
      }
    }
  };

  useEffect(() => {
    loadReferral();
  }, []);

  const submitCare = async (e) => {
    e.preventDefault();
    setSending(true);
    setCareError('');
    setSent(false);
    try {
      await api.post('/support/contact/', { subject, message: message.trim() });
      setSent(true);
      setMessage('');
      setTimeout(() => setSent(false), 4000);
    } catch (err) {
      const apiError = err.response?.data?.error;
      const details = apiError?.details;
      let detail = '';
      if (typeof details === 'string') detail = details;
      else if (details && typeof details === 'object') {
        const first = Object.values(details)[0];
        detail = Array.isArray(first) ? first[0] : (typeof first === 'string' ? first : '');
      }
      setCareError(detail || apiError?.message || 'Could not send message. Try again.');
    } finally {
      setSending(false);
    }
  };

  const copyInvite = async () => {
    const ok = await shareOrCopy(inviteUrl);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const changeLanguage = (value) => {
    setLanguageState(setLang(value));
  };

  const checkUpdate = async () => {
    setChecking(true);
    setUpdateMsg('');
    setUpdateOk(false);
    try {
      const res = await fetch(`/?fet-update-check=${Date.now()}`, { cache: 'no-store' });
      const html = await res.text();
      const match = html.match(/<script[^>]+type="module"[^>]+src="([^"]+index-[^"]+\.js)"[^>]*>/i);
      const remote = match ? match[1].split('/').pop() : null;
      const current = Array.from(document.querySelectorAll('script[type="module"]'))
        .map((s) => s.src.split('/').pop())
        .find((s) => s && s.includes('index-'));
      if (remote && current && remote !== current) {
        setUpdateOk(true);
        setUpdateMsg('A new version is available. Reloading...');
        setTimeout(() => window.location.reload(), 1500);
      } else {
        setUpdateMsg("You're up to date.");
      }
    } catch {
      setUpdateMsg('Could not check for updates. Try reloading the page.');
    } finally {
      setChecking(false);
    }
  };

  const tabs = [
    { id: 'care', label: t('customerCare'), icon: MessageCircle },
    ...(inviteAvailable ? [{ id: 'invite', label: t('inviteFriend'), icon: UserPlus }] : []),
    { id: 'language', label: t('language'), icon: Globe },
    { id: 'update', label: t('appUpdate'), icon: RefreshCw },
  ];

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      <SectionHeader
        area="hub"
        icon={SettingsIcon}
        title={t('settings')}
        subtitle={t('settingsSubtitle')}
      />

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const activeTab = active === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActive(tab.id)}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-[13px] font-medium transition-colors ${
                activeTab
                  ? 'bg-primary text-white shadow-sm'
                  : 'bg-surface text-text-secondary hover:bg-page-bg hover:text-text-primary border border-border-default'
              }`}
            >
              <Icon size={16} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {active === 'care' && (
        <Card accent="hub">
          <CardHead title="Customer Care" subtitle="Send a message to our support team" />
          <CardBody>
            <form onSubmit={submitCare} className="space-y-4">
              <div>
                <label className="fet-label">Topic</label>
                <select
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="fet-select"
                  disabled={sending}
                >
                  <option value="general">General inquiry</option>
                  <option value="account">Account / Login</option>
                  <option value="attendance">Attendance</option>
                  <option value="fees">Fees / Payments</option>
                  <option value="technical">Technical issue</option>
                  <option value="feedback">Feedback</option>
                </select>
              </div>
              <div>
                <label className="fet-label">Message</label>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  className="fet-input"
                  rows={6}
                  placeholder="Describe your issue or question in detail..."
                  required
                  minLength={10}
                  disabled={sending}
                />
                <p className="mt-1 text-[11px] text-text-secondary">{message.trim().length}/10 minimum</p>
              </div>
              {careError && <Callout tone="bad">{careError}</Callout>}
              {sent && <Callout tone="ok">Message sent successfully. Our team will get back to you soon.</Callout>}
              <div className="flex justify-end">
                <button type="submit" disabled={sending || message.trim().length < 10} className="fet-btn-primary flex items-center gap-2">
                  <Send size={16} />
                  {sending ? 'Sending...' : 'Send Message'}
                </button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {active === 'invite' && (
        <Card accent="hub">
          <CardHead title="Invite a Friend" subtitle="Share your invite link and earn rewards when they join" />
          <CardBody className="space-y-4">
            <Callout tone="info">
              <div className="flex items-start gap-2">
                <Info size={16} className="mt-0.5" />
                <div>
                  <p className="font-medium">How it works</p>
                  <p className="mt-1 text-[12px]">
                    Share your unique link with friends. When they sign up using your link, you'll be rewarded.
                    Admins can track referrals for reward distribution.
                  </p>
                </div>
              </div>
            </Callout>

            {refError && <Callout tone="bad">{refError}</Callout>}

            <div>
              <label className="fet-label">Your Invite Link</label>
              <div className="flex flex-col sm:flex-row gap-2">
                <div className="relative flex-1">
                  <Link2 size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
                  <input
                    type="text"
                    value={inviteUrl}
                    readOnly
                    className="fet-input pl-10"
                    onClick={(e) => e.target.select()}
                  />
                </div>
                <button type="button" onClick={copyInvite} className="fet-btn-primary flex items-center justify-center gap-2 whitespace-nowrap">
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                  {copied ? 'Copied!' : 'Copy / Share'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border-default p-4">
                <p className="text-[12px] text-text-secondary">Invites Sent</p>
                <p className="mt-1 text-2xl font-bold text-text-primary">{referral?.invites_sent || 0}</p>
              </div>
              <div className="rounded-xl border border-border-default p-4">
                <p className="text-[12px] text-text-secondary">Successful Signups</p>
                <p className="mt-1 text-2xl font-bold text-text-primary">{referral?.successful_signups || 0}</p>
              </div>
            </div>

            <p className="text-[11px] text-text-secondary">
              Referral code: <span className="font-mono">{referral?.code || currentUser?.id || '—'}</span>
            </p>
          </CardBody>
        </Card>
      )}

      {active === 'language' && (
        <Card accent="hub">
          <CardHead title="Language" subtitle="Choose your preferred language" />
          <CardBody className="space-y-4">
            <div>
              <label className="fet-label">{t('systemLanguage')}</label>
              <select value={language} onChange={(e) => changeLanguage(e.target.value)} className="fet-select max-w-xs">
                <option value="en">{t('english')}</option>
                <option value="fr">{t('french')}</option>
              </select>
              <p className="mt-2 text-[12px] text-text-secondary">{t('languageSaved')}</p>
            </div>
          </CardBody>
        </Card>
      )}

      {active === 'update' && (
        <Card accent="hub">
          <CardHead title="App Update" subtitle="Manually check for a newer version of the platform" />
          <CardBody className="space-y-4">
            <Callout tone="info">
              <div className="flex items-start gap-2">
                <Info size={16} className="mt-0.5" />
                <div>
                  <p className="font-medium">Force update check</p>
                  <p className="mt-1 text-[12px]">
                    If the update pop-up didn't appear after a new deployment, use this to check and reload
                    to the latest version.
                  </p>
                </div>
              </div>
            </Callout>

            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-xl border border-border-default p-4">
              <div>
                <p className="font-medium text-text-primary">Current session</p>
                <p className="mt-1 text-[12px] text-text-secondary">{t('appBuild')}: {APP_BUILD}</p>
              </div>
              <button type="button" onClick={checkUpdate} disabled={checking} className="fet-btn-primary flex items-center gap-2">
                <RefreshCw size={16} className={checking ? 'animate-spin' : ''} />
                {checking ? 'Checking...' : 'Check for updates'}
              </button>
            </div>

            {updateMsg && (
              <Callout tone={updateOk ? 'ok' : 'mu'}>
                {updateMsg}
              </Callout>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
};

export default Settings;


export const SupportMessagesPanel = () => {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get('/admin/support/');
        setMessages(Array.isArray(res.data) ? res.data : res.data?.data || []);
      } catch (err) {
        setError(err.response?.data?.error?.message || 'Could not load messages.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <Card accent="hub">
      <CardHead title="Customer Messages" subtitle="Messages sent from Settings > Customer Care" />
      <CardBody>
        {loading ? <p className="text-[13px] text-text-secondary">Loading...</p> : null}
        {error ? <Callout tone="bad">{error}</Callout> : null}
        {!loading && !error && messages.length === 0 && <p className="text-[13px] text-text-secondary">No messages yet.</p>}
        <div className="space-y-3">
          {messages.map((m) => (
            <div key={m.id} className="rounded-xl border border-border-default p-4">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-text-primary">{m.actor_name || m.actor_email || 'Unknown'}</p>
                  <p className="text-[12px] text-text-secondary">{m.actor_email}</p>
                </div>
                <Pill tone="mu">{m.subject || 'general'}</Pill>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-[13px] text-text-primary">{m.message}</p>
              <p className="mt-2 text-[11px] text-text-secondary">{m.created_at ? new Date(m.created_at).toLocaleString() : ''}</p>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
};
