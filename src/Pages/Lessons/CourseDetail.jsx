import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Loader2, Upload, Download, Trash2, FileText, FileImage,
  FileSpreadsheet, FileArchive, Presentation, Megaphone, FolderOpen, Send,
  ClipboardCheck, ChevronDown, ChevronRight, RotateCcw, Award,
  CheckCircle2, Plus, AlertCircle,
} from 'lucide-react';
import { learningApi } from '../../lib/learning';
import { announcementsApi } from '../../lib/announcements';
import { normalizeRole } from '../../lib/profile';
import CourseDelegatesPanel from '../../components/Attendance/CourseDelegatesPanel';
import AssessmentPanel from '../../components/Assessment/AssessmentPanel';

const PALETTES = [
  ['#B39DDB', '#7E57C2'],
  ['#81C784', '#388E3C'],
  ['#FFB74D', '#EF6C00'],
  ['#4FC3F7', '#0277BD'],
  ['#E57373', '#C62828'],
  ['#9575CD', '#512DA8'],
  ['#4DB6AC', '#00796B'],
  ['#F06292', '#AD1457'],
];

const hashIdx = (str) => {
  let h = 0;
  for (let i = 0; i < str.length; i += 1) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
};

const formatBytes = (bytes) => {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const formatDate = (iso) => {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
};

const formatDateTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} at ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
};

const toLocalDateTimeInput = (iso) => {
  if (!iso) return '';
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

const BUCKET_ORDER = ['This week', 'Last week', 'Earlier this month', 'Older'];

const bucketFor = (iso) => {
  const d = new Date(iso).getTime();
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  const diffDays = (now - d) / dayMs;
  if (diffDays < 0 || diffDays <= 7) return 'This week';
  if (diffDays <= 14) return 'Last week';
  if (diffDays <= 30) return 'Earlier this month';
  return 'Older';
};

const fileIcon = (name = '') => {
  const ext = name.split('.').pop().toLowerCase();
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return <FileImage size={20} className="text-primary" />;
  if (['xls', 'xlsx', 'csv'].includes(ext)) return <FileSpreadsheet size={20} className="text-success" />;
  if (['zip'].includes(ext)) return <FileArchive size={20} className="text-warning" />;
  if (['ppt', 'pptx'].includes(ext)) return <Presentation size={20} className="text-danger" />;
  return <FileText size={20} className="text-primary" />;
};

const CourseDetail = ({ user }) => {
  const { offeringId } = useParams();
  const navigate = useNavigate();
  const [course, setCourse] = useState(null);
  const [courseLoading, setCourseLoading] = useState(true);
  const [courseError, setCourseError] = useState('');

  const [tab, setTab] = useState('stream');

  const [materials, setMaterials] = useState([]);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadForm, setUploadForm] = useState({ title: '', description: '', file: null });

  const [announcements, setAnnouncements] = useState([]);
  const [annLoading, setAnnLoading] = useState(false);
  const [annForm, setAnnForm] = useState({ title: '', content: '' });
  const [postingAnn, setPostingAnn] = useState(false);
  const [editingAnnouncement, setEditingAnnouncement] = useState(null);
  const [savingAnnouncement, setSavingAnnouncement] = useState(false);

  const [assignments, setAssignments] = useState([]);
  const [asgnLoading, setAsgnLoading] = useState(false);
  const [newAsgnOpen, setNewAsgnOpen] = useState(false);
  const [creatingAsgn, setCreatingAsgn] = useState(false);
  const [asgnForm, setAsgnForm] = useState({
    title: '', description: '', points_possible: '', due_at: '', allow_late: false, max_submissions: 1, file: null,
  });
  const [expandedAssignment, setExpandedAssignment] = useState(null);
  const [submissions, setSubmissions] = useState({});
  const [subsLoading, setSubsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitForm, setSubmitForm] = useState({ note: '', file: null });
  const [grades, setGrades] = useState({});
  const [savingGrade, setSavingGrade] = useState(null);
  const [activeSubmitAssignment, setActiveSubmitAssignment] = useState(null);
  const [editingAssignment, setEditingAssignment] = useState(null);
  const [savingAssignment, setSavingAssignment] = useState(false);


  const [message, setMessage] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  const role = normalizeRole(user?.role);
  const isStaff = role === 'lecturer' || role === 'admin';

  const notify = (msg) => {
    setMessage(msg);
    setErrorMsg('');
    window.setTimeout(() => setMessage(''), 4000);
  };
  const notifyError = (msg) => {
    setErrorMsg(msg);
    setMessage('');
  };

  const loadMaterials = useCallback(async () => {
    setMaterialsLoading(true);
    try {
      const data = await learningApi.getMaterials(offeringId);
      setMaterials(data || []);
    } catch (err) {
      notifyError('Failed to load materials.');
    } finally {
      setMaterialsLoading(false);
    }
  }, [offeringId]);

  const loadAnnouncements = useCallback(async () => {
    setAnnLoading(true);
    try {
      const data = await announcementsApi.listForCourse(offeringId);
      setAnnouncements(data || []);
    } catch (err) {
      notifyError('Failed to load announcements.');
    } finally {
      setAnnLoading(false);
    }
  }, [offeringId]);

  const loadAssignments = useCallback(async () => {
    setAsgnLoading(true);
    try {
      const data = await learningApi.getAssignments(offeringId);
      setAssignments(data || []);
    } catch (err) {
      notifyError('Failed to load assignments.');
    } finally {
      setAsgnLoading(false);
    }
  }, [offeringId]);


  const loadSubmissions = async (assignment) => {
    setExpandedAssignment(assignment.id);
    setSubsLoading(true);
    try {
      const data = await learningApi.getSubmissions(assignment.id);
      setSubmissions((prev) => ({ ...prev, [assignment.id]: data || [] }));
    } catch (err) {
      notifyError('Failed to load submissions.');
    } finally {
      setSubsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setCourseLoading(true);
      setCourseError('');
      try {
        const data = await learningApi.getCourse(offeringId);
        if (!cancelled) setCourse(data);
      } catch (err) {
        if (!cancelled) setCourseError('Course not found or you lack access.');
      } finally {
        if (!cancelled) setCourseLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [offeringId]);

  useEffect(() => {
    if (tab === 'materials' || tab === 'stream') loadMaterials();
    if (tab === 'announcements' || tab === 'stream') loadAnnouncements();
    if (tab === 'assignments' || tab === 'stream') loadAssignments();
  }, [tab, loadMaterials, loadAnnouncements, loadAssignments]);

  const handleUpload = async () => {
    if (!uploadForm.title.trim() || !uploadForm.file) {
      notifyError('Please provide a title and choose a file.');
      return;
    }
    setUploading(true);
    setErrorMsg('');
    try {
      const uploaded = await learningApi.uploadFile(uploadForm.file);
      await learningApi.createMaterial({
        title: uploadForm.title.trim(),
        description: uploadForm.description,
        course_offering: offeringId,
        file: uploaded.id,
        visibility: 'COURSE',
      });
      setUploadForm({ title: '', description: '', file: null });
      notify('Material uploaded.');
      loadMaterials();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteMaterial = async (materialId) => {
    if (!window.confirm('Delete this material?')) return;
    try {
      await learningApi.deleteMaterial(materialId);
      notify('Material deleted.');
      loadMaterials();
    } catch (err) {
      notifyError('Failed to delete material.');
    }
  };

  const handlePostAnnouncement = async () => {
    if (!annForm.title.trim() || !annForm.content.trim()) {
      notifyError('Please add a title and message.');
      return;
    }
    setPostingAnn(true);
    setErrorMsg('');
    try {
      await announcementsApi.create({
        scope_type: 'COURSE',
        course_offering: offeringId,
        title: annForm.title.trim(),
        content: annForm.content.trim(),
      });
      setAnnForm({ title: '', content: '' });
      notify('Announcement published.');
      loadAnnouncements();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to post announcement.');
    } finally {
      setPostingAnn(false);
    }
  };

  const handleDeleteAnnouncement = async (id) => {
    if (!window.confirm('Delete this announcement?')) return;
    try {
      await announcementsApi.remove(id);
      notify('Announcement deleted.');
      loadAnnouncements();
    } catch (err) {
      notifyError('Failed to delete announcement.');
    }
  };

  const handleSaveAnnouncement = async () => {
    if (!editingAnnouncement?.title.trim() || !editingAnnouncement?.content.trim()) {
      notifyError('Please add a title and message.');
      return;
    }
    setSavingAnnouncement(true);
    try {
      await announcementsApi.update(editingAnnouncement.id, {
        title: editingAnnouncement.title.trim(),
        content: editingAnnouncement.content.trim(),
      });
      setEditingAnnouncement(null);
      notify('Announcement updated.');
      loadAnnouncements();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to update announcement.');
    } finally {
      setSavingAnnouncement(false);
    }
  };

  const handlePinAnnouncement = async (ann) => {
    try {
      await announcementsApi.setPinned(ann.id, !ann.is_pinned);
      loadAnnouncements();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to update the pin.');
    }
  };

  const handleMarkRead = async (ann) => {
    try {
      await announcementsApi.markRead(ann.id);
      loadAnnouncements();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to mark announcement as read.');
    }
  };

  const handleCreateAssignment = async () => {
    if (!asgnForm.title.trim()) {
      notifyError('Please give the assignment a title.');
      return;
    }
    setCreatingAsgn(true);
    setErrorMsg('');
    try {
      let attachmentId = null;
      if (asgnForm.file) {
        const uploaded = await learningApi.uploadFile(asgnForm.file);
        attachmentId = uploaded.id;
      }
      await learningApi.createAssignment(offeringId, {
        title: asgnForm.title.trim(),
        description: asgnForm.description,
        points_possible: asgnForm.points_possible === '' ? 0 : Number(asgnForm.points_possible),
        due_at: asgnForm.due_at ? new Date(asgnForm.due_at).toISOString() : null,
        allow_late: asgnForm.allow_late,
        max_submissions: Math.max(0, Number(asgnForm.max_submissions) || 0),
        ...(attachmentId ? { attachment: attachmentId } : {}),
      });
      setAsgnForm({ title: '', description: '', points_possible: '', due_at: '', allow_late: false, max_submissions: 1, file: null });
      setNewAsgnOpen(false);
      notify('Assignment created.');
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to create the assignment.');
    } finally {
      setCreatingAsgn(false);
    }
  };

  const handleSaveAssignment = async () => {
    if (!editingAssignment?.title.trim()) {
      notifyError('Please give the assignment a title.');
      return;
    }
    setSavingAssignment(true);
    try {
      await learningApi.updateAssignment(editingAssignment.id, {
        title: editingAssignment.title.trim(),
        description: editingAssignment.description,
        points_possible: Number(editingAssignment.points_possible) || 0,
        due_at: editingAssignment.due_at || null,
        allow_late: editingAssignment.allow_late,
        max_submissions: Number(editingAssignment.max_submissions) || 0,
      });
      setEditingAssignment(null);
      notify('Assignment updated.');
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to update assignment.');
    } finally {
      setSavingAssignment(false);
    }
  };

  const handleArchiveAssignment = async (assignment) => {
    if (!window.confirm(`Archive "${assignment.title}"? Students will no longer be able to turn in work.`)) return;
    try {
      await learningApi.deleteAssignment(assignment.id);
      notify('Assignment archived.');
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to archive assignment.');
    }
  };

  const handleSubmitWork = async (assignment) => {
    setSubmitting(true);
    setErrorMsg('');
    try {
      let fileId = null;
      if (submitForm.file) {
        const uploaded = await learningApi.uploadFile(submitForm.file);
        fileId = uploaded.id;
      }
      await learningApi.submitAssignment(assignment.id, {
        ...(fileId ? { file: fileId } : {}),
        note: submitForm.note,
      });
      setSubmitForm({ note: '', file: null });
      setActiveSubmitAssignment(null);
      notify('Work submitted.');
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Submission failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleGrade = async (submission) => {
    if (savingGrade) return;
    const entry = grades[submission.id] || { grade: submission.grade || '', feedback: submission.feedback || '' };
    setSavingGrade(submission.id);
    setErrorMsg('');
    try {
      await learningApi.gradeSubmission(submission.id, { grade: entry.grade, feedback: entry.feedback });
      notify('Grade saved.');
      if (expandedAssignment) await loadSubmissions({ id: expandedAssignment });
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to save grade.');
    } finally {
      setSavingGrade(null);
    }
  };

  const handleReturn = async (assignment, submission) => {
    if (!window.confirm(`Return ${submission.student_name}'s work? They will be able to resubmit.`)) return;
    setErrorMsg('');
    try {
      await learningApi.gradeSubmission(submission.id, { status: 'RETURNED' });
      notify(`${submission.student_name}'s work returned.`);
      await loadSubmissions(assignment);
      loadAssignments();
    } catch (err) {
      notifyError(err?.response?.data?.error?.message || 'Failed to return the work.');
    }
  };

  const statusChip = (assignment) => {
    if (assignment.status === 'ARCHIVED') return { label: 'Archived', tone: 'warning' };
    const mine = assignment.my_submission;
    const past = assignment.due_at && new Date(assignment.due_at) < new Date();
    if (mine) {
      if (mine.status === 'GRADED') return { label: 'Graded', tone: 'success' };
      if (mine.status === 'RETURNED') return { label: 'Returned - resubmit', tone: 'warning' };
      if (mine.is_late) return { label: 'Turned in late', tone: 'warning' };
      return { label: 'Turned in', tone: 'success' };
    }
    if (past && !assignment.allow_late) return { label: 'Missing', tone: 'danger' };
    return { label: 'Open', tone: 'info' };
  };


  if (courseLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (courseError) {
    return (
      <div className="fet-card p-12 text-center">
        <FolderOpen size={48} className="mx-auto opacity-40 text-text-secondary" />
        <p className="mt-4 font-semibold text-text-primary">{courseError}</p>
        <button className="fet-btn-secondary mt-4" onClick={() => navigate('/lessons')}>
          <ArrowLeft size={16} /> Back to classrooms
        </button>
      </div>
    );
  }

  const [from, to] = PALETTES[hashIdx(course.course_code || course.id) % PALETTES.length];
  const streamItems = [
    ...announcements.map((item) => ({ id: item.id, type: 'Announcement', title: item.title, description: item.content, at: item.published_at || item.created_at, tab: 'announcements', pinned: item.is_pinned })),
    ...assignments.filter((item) => item.status === 'ACTIVE').map((item) => ({ id: item.id, type: 'Assignment', title: item.title, description: item.description, at: item.created_at, tab: 'assignments', due_at: item.due_at })),
    ...materials.map((item) => ({ id: item.id, type: 'Material', title: item.title, description: item.description, at: item.created_at, tab: 'materials' })),
  ].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || new Date(b.at) - new Date(a.at));
  const todo = assignments.filter((item) => item.status === 'ACTIVE' && (!item.my_submission || item.my_submission.status === 'RETURNED'));
  const toReview = assignments.reduce((total, item) => total + (item.pending_review_count || 0), 0);
  const grouped = BUCKET_ORDER.map((bucket) => ({
    bucket,
    items: materials.filter((m) => bucketFor(m.created_at) === bucket),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate('/lessons')}
        className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
      >
        <ArrowLeft size={16} /> All classrooms
      </button>

      {/* Course banner header */}
      <div
        className="rounded-2xl p-6 text-white"
        style={{ backgroundImage: `linear-gradient(120deg, ${from}, ${to})` }}
      >
        <span className="inline-block text-xs font-semibold tracking-widest uppercase bg-white/15 rounded-full px-3 py-1">
          {course.course_code || course.course_title}
        </span>
        <h2 className="mt-3 text-2xl md:text-3xl font-bold leading-tight">{course.course_title}</h2>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-white/85">
          <span>{course.lecturer_name || 'Staff'}</span>
          <span>{course.semester_name}</span>
        </div>
      </div>

      {message && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-xl text-sm">{message}</div>
      )}
      {errorMsg && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm">{errorMsg}</div>
      )}

      {/* Tabs — scroll horizontally instead of pushing the page wide */}
      <div className="flex gap-1 border-b border-border-default overflow-x-auto">
        {[
          { key: 'stream', label: 'Stream', icon: FolderOpen },
          { key: 'materials', label: `Materials (${materials.length})`, icon: FileText },
          { key: 'announcements', label: `Announcements (${announcements.length})`, icon: Megaphone },
          { key: 'assignments', label: `Assignments (${assignments.length})`, icon: ClipboardCheck },
          { key: 'marks', label: 'Marks', icon: Award },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex shrink-0 items-center gap-2 whitespace-nowrap px-4 py-2.5 text-sm font-medium rounded-t-xl border-b-2 transition-colors ${
              tab === t.key
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            <t.icon size={16} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'stream' && (
        <div className="space-y-4">
          {isStaff && course?.course ? (
            <CourseDelegatesPanel courseId={course.course} />
          ) : null}
          <div className="fet-card p-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-text-primary">{isStaff ? 'Work to review' : 'Your work'}</h3>
              <p className="text-sm text-text-secondary mt-1">
                {isStaff ? `${toReview} submission${toReview === 1 ? '' : 's'} awaiting a grade` : `${todo.length} assignment${todo.length === 1 ? '' : 's'} to do`}
              </p>
            </div>
            <button className="fet-btn-secondary" onClick={() => setTab('assignments')}>Open assignments</button>
          </div>
          {(materialsLoading || annLoading || asgnLoading) && <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>}
          {!materialsLoading && !annLoading && !asgnLoading && streamItems.length === 0 && (
            <div className="fet-card p-10 text-center text-text-secondary">Nothing has been posted in this classroom yet.</div>
          )}
          {streamItems.map((item) => (
            <button key={`${item.type}-${item.id}`} onClick={() => setTab(item.tab)} className="fet-card p-5 w-full text-left hover:border-primary">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold text-primary">{item.pinned ? 'Pinned · ' : ''}{item.type}</span>
                <span className="text-xs text-text-secondary">{formatDate(item.at)}</span>
              </div>
              <h4 className="font-semibold text-text-primary mt-2">{item.title}</h4>
              {item.description && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{item.description}</p>}
              {item.due_at && <p className="text-xs text-text-secondary mt-2">Due {formatDateTime(item.due_at)}</p>}
            </button>
          ))}
        </div>
      )}

      {/* ---------- MATERIALS ---------- */}
      {tab === 'materials' && (
        <div className="space-y-4">
          {isStaff && (
            <div className="fet-card p-5">
              <h3 className="font-semibold text-text-primary mb-3 flex items-center gap-2">
                <Upload size={16} className="text-primary" /> Share material
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <input
                  type="text"
                  value={uploadForm.title}
                  onChange={(e) => setUploadForm({ ...uploadForm, title: e.target.value })}
                  className="fet-input"
                  placeholder="Title *"
                />
                <input
                  type="text"
                  value={uploadForm.description}
                  onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                  className="fet-input"
                  placeholder="Description (optional)"
                />
                <input
                  type="file"
                  onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files[0] })}
                  className="fet-input"
                />
              </div>
              <div className="mt-3 flex items-center justify-between">
                {uploadForm.file && (
                  <span className="text-xs text-text-secondary truncate max-w-[60%]">
                    {uploadForm.file.name} · {formatBytes(uploadForm.file.size)}
                  </span>
                )}
                <button
                  onClick={handleUpload}
                  disabled={uploading || !uploadForm.title.trim() || !uploadForm.file}
                  className="fet-btn-primary flex items-center gap-2"
                >
                  {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload size={16} />}
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
              </div>
            </div>
          )}

          {materialsLoading && (
            <div className="flex justify-center py-10">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
          )}

          {!materialsLoading && materials.length === 0 && (
            <div className="fet-card p-10 text-center">
              <FileText size={44} className="mx-auto opacity-40 text-text-secondary" />
              <p className="mt-3 font-semibold text-text-primary">No materials yet</p>
              <p className="text-sm text-text-secondary mt-1">Materials shared here will appear in this course.</p>
            </div>
          )}

          {!materialsLoading && grouped.map((group) => (
            <div key={group.bucket}>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary px-1 mb-2">
                {group.bucket}
              </h4>
              <div className="space-y-2">
                {group.items.map((material) => (
                  <div
                    key={material.id}
                    className="flex items-center justify-between gap-3 p-4 bg-white rounded-xl border border-border-default shadow-card hover:shadow-card-hover transition-shadow"
                  >
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="p-2.5 bg-primary/5 rounded-lg shrink-0">{fileIcon(material.file_info?.original_name)}</div>
                      <div className="min-w-0">
                        <p className="font-medium text-text-primary truncate">{material.title}</p>
                        <p className="text-sm text-text-secondary truncate">{material.description || 'No description'}</p>
                        <p className="text-xs text-text-secondary mt-0.5">
                          {material.uploader_name} · {formatDate(material.created_at)}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {material.file_info && (
                        <a
                          href={learningApi.getDownloadUrl(material.file_info.id)}
                          target="_blank"
                          rel="noreferrer"
                          className="fet-btn-secondary flex items-center gap-1 text-sm"
                        >
                          <Download size={15} /> <span className="hidden sm:inline">{formatBytes(material.file_info.size_bytes)}</span>
                        </a>
                      )}
                      {isStaff && (
                        <button
                          onClick={() => handleDeleteMaterial(material.id)}
                          className="p-2 hover:bg-red-50 text-red-500 rounded-lg"
                          title="Delete material"
                        >
                          <Trash2 size={17} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ---------- ANNOUNCEMENTS ---------- */}
      {tab === 'announcements' && (
        <div className="space-y-4">
          {isStaff && (
            <div className="fet-card p-5">
              <h3 className="font-semibold text-text-primary mb-3 flex items-center gap-2">
                <Megaphone size={16} className="text-primary" /> Post announcement
              </h3>
              <input
                type="text"
                value={annForm.title}
                onChange={(e) => setAnnForm({ ...annForm, title: e.target.value })}
                className="fet-input mb-3"
                placeholder="Announcement title *"
              />
              <textarea
                value={annForm.content}
                onChange={(e) => setAnnForm({ ...annForm, content: e.target.value })}
                className="fet-input min-h-[90px]"
                placeholder="Message to the class * (e.g. Guest lecture this Friday in Room 204)"
              />
              <div className="mt-3 flex justify-end">
                <button
                  onClick={handlePostAnnouncement}
                  disabled={postingAnn}
                  className="fet-btn-primary flex items-center gap-2"
                >
                  {postingAnn ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send size={16} />}
                  Post
                </button>
              </div>
            </div>
          )}

          {annLoading && (
            <div className="flex justify-center py-10">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
          )}

          {!annLoading && announcements.length === 0 && (
            <div className="fet-card p-10 text-center">
              <Megaphone size={44} className="mx-auto opacity-40 text-text-secondary" />
              <p className="mt-3 font-semibold text-text-primary">No announcements yet</p>
              <p className="text-sm text-text-secondary mt-1">Course announcements will appear here.</p>
            </div>
          )}

          {!annLoading && announcements.map((ann) => (
            <div key={ann.id} className="fet-card p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="font-bold text-text-primary">{ann.title}</h4>
                  <p className="text-xs text-text-secondary mt-0.5">
                    {ann.creator_name} · {formatDateTime(ann.published_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {ann.is_pinned && <span className="text-xs font-medium text-primary">Pinned</span>}
                  {ann.can_manage && (
                    <>
                      <button onClick={() => handlePinAnnouncement(ann)} className="text-xs text-primary hover:underline">
                        {ann.is_pinned ? 'Unpin' : 'Pin'}
                      </button>
                      <button onClick={() => setEditingAnnouncement({ id: ann.id, title: ann.title, content: ann.content })} className="text-xs text-primary hover:underline">Edit</button>
                      <button onClick={() => handleDeleteAnnouncement(ann.id)} className="p-2 hover:bg-red-50 text-red-500 rounded-lg" title="Archive announcement">
                        <Trash2 size={16} />
                      </button>
                    </>
                  )}
                  {!isStaff && !ann.is_read && (
                    <button onClick={() => handleMarkRead(ann)} className="text-xs text-primary hover:underline">Mark read</button>
                  )}
                </div>
              </div>
              <p className="mt-2 text-sm text-text-primary whitespace-pre-wrap leading-relaxed">{ann.content}</p>
              {editingAnnouncement?.id === ann.id && (
                <div className="mt-4 space-y-2 border-t border-border-default pt-4">
                  <input className="fet-input" value={editingAnnouncement.title} onChange={(e) => setEditingAnnouncement({ ...editingAnnouncement, title: e.target.value })} aria-label="Announcement title" />
                  <textarea className="fet-input min-h-[90px]" value={editingAnnouncement.content} onChange={(e) => setEditingAnnouncement({ ...editingAnnouncement, content: e.target.value })} aria-label="Announcement message" />
                  <div className="flex gap-2 justify-end">
                    <button className="fet-btn-secondary" onClick={() => setEditingAnnouncement(null)}>Cancel</button>
                    <button className="fet-btn-primary" disabled={savingAnnouncement} onClick={handleSaveAnnouncement}>Save changes</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ---------- ASSIGNMENTS ---------- */}
      {tab === 'assignments' && (
        <div className="space-y-4">
          {isStaff && (
            <div className="fet-card p-5">
              <button
                onClick={() => setNewAsgnOpen(!newAsgnOpen)}
                className="flex items-center gap-2 font-semibold text-text-primary"
              >
                {newAsgnOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <ClipboardCheck size={16} className="text-primary" /> Create assignment
              </button>
              {newAsgnOpen && (
                <div className="mt-4 space-y-3">
                  <input
                    type="text"
                    value={asgnForm.title}
                    onChange={(e) => setAsgnForm({ ...asgnForm, title: e.target.value })}
                    className="fet-input"
                    placeholder="Title *"
                  />
                  <textarea
                    value={asgnForm.description}
                    onChange={(e) => setAsgnForm({ ...asgnForm, description: e.target.value })}
                    className="fet-input min-h-[70px]"
                    placeholder="Instructions for the class (optional)"
                  />
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    <label className="flex flex-col gap-1">
                      <span className="fet-label">Points</span>
                      <input
                        type="number"
                        min="0"
                        value={asgnForm.points_possible}
                        onChange={(e) => setAsgnForm({ ...asgnForm, points_possible: e.target.value })}
                        className="fet-input"
                        placeholder="e.g. 20"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="fet-label">Due date & time</span>
                      <input
                        type="datetime-local"
                        value={asgnForm.due_at}
                        onChange={(e) => setAsgnForm({ ...asgnForm, due_at: e.target.value })}
                        className="fet-input"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="fet-label">Submission limit</span>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          min="0"
                          value={asgnForm.max_submissions}
                          onChange={(e) => setAsgnForm({ ...asgnForm, max_submissions: e.target.value })}
                          className="fet-input"
                        />
                        <span className="text-xs text-text-secondary">0 = unlimited</span>
                      </div>
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="fet-label">Attachment (optional)</span>
                      <input
                        type="file"
                        onChange={(e) => setAsgnForm({ ...asgnForm, file: e.target.files[0] })}
                        className="fet-input"
                      />
                    </label>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-text-primary">
                    <input
                      type="checkbox"
                      checked={asgnForm.allow_late}
                      onChange={(e) => setAsgnForm({ ...asgnForm, allow_late: e.target.checked })}
                      className="h-4 w-4 accent-primary"
                    />
                    Accept submissions after the due date
                  </label>
                  <div className="flex justify-end">
                    <button
                      onClick={handleCreateAssignment}
                      disabled={creatingAsgn || !asgnForm.title.trim()}
                      className="fet-btn-primary flex items-center gap-2"
                    >
                      {creatingAsgn ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send size={16} />}
                      Create
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {asgnLoading && (
            <div className="flex justify-center py-10">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
          )}

          {!asgnLoading && assignments.length === 0 && (
            <div className="fet-card p-10 text-center">
              <ClipboardCheck size={44} className="mx-auto opacity-40 text-text-secondary" />
              <p className="mt-3 font-semibold text-text-primary">No assignments yet</p>
              <p className="text-sm text-text-secondary mt-1">
                {isStaff ? 'Create an assignment to get started.' : 'Assignments posted by your lecturer will appear here.'}
              </p>
            </div>
          )}

          {!asgnLoading && assignments.map((asgn) => {
            const chip = statusChip(asgn);
            const tone = {
              success: 'bg-green-50 text-green-700 border-green-200',
              warning: 'bg-amber-50 text-amber-700 border-amber-200',
              danger: 'bg-red-50 text-red-700 border-red-200',
              info: 'bg-blue-50 text-blue-700 border-blue-200',
            }[chip.tone] || 'bg-blue-50 text-blue-700 border-blue-200';
            const past = asgn.due_at && new Date(asgn.due_at) < new Date();
            const maxSub = asgn.max_submissions;
            const used = asgn.attempts_used || 0;
            const limitReached = maxSub !== 0 && used >= maxSub;
            const canSubmit = asgn.status === 'ACTIVE' && !(past && !asgn.allow_late) && !limitReached;
            const hasTurnedIn = asgn.my_submission && asgn.my_submission.status !== 'RETURNED';
            const showSubmitForm = !hasTurnedIn || activeSubmitAssignment === asgn.id;
            const expanded = expandedAssignment === asgn.id;
            const subs = submissions[asgn.id] || [];
            return (
              <div key={asgn.id} className="fet-card p-5">
                {/* Header */}
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-bold text-text-primary">{asgn.title}</h4>
                      <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${tone}`}>{chip.label}</span>
                    </div>
                    <p className="text-sm text-text-secondary mt-1 whitespace-pre-wrap">{asgn.description}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary">
                      <span>{asgn.points_possible ? `${asgn.points_possible} pts` : 'No points'}</span>
                      {asgn.due_at && (
                        <span>
                          Due {formatDateTime(asgn.due_at)}
                          {asgn.allow_late && ' (late accepted)'}
                        </span>
                      )}
                      {maxSub !== 0 ? (
                        <span>{used}/{maxSub} submission{maxSub === 1 ? '' : 's'} used</span>
                      ) : (
                        <span>Unlimited submissions</span>
                      )}
                      {isStaff && (
                        <span>{asgn.submissions_count} submitted · {asgn.graded_count} graded</span>
                      )}
                    </div>
                  </div>
                  {asgn.attachment_info && (
                    <a
                      href={learningApi.getDownloadUrl(asgn.attachment_info.id)}
                      target="_blank"
                      rel="noreferrer"
                      className="fet-btn-secondary flex items-center gap-1 text-sm shrink-0"
                    >
                      <Download size={15} /> Brief
                    </a>
                  )}
                </div>

                {isStaff && asgn.status === 'ACTIVE' && (
                  <div className="mt-3 flex gap-3 text-sm">
                    <button className="text-primary hover:underline" onClick={() => setEditingAssignment({
                      id: asgn.id,
                      title: asgn.title,
                      description: asgn.description,
                      points_possible: asgn.points_possible,
                      due_at: asgn.due_at,
                      allow_late: asgn.allow_late,
                      max_submissions: asgn.max_submissions,
                    })}>Edit assignment</button>
                    <button className="text-red-600 hover:underline" onClick={() => handleArchiveAssignment(asgn)}>Archive</button>
                  </div>
                )}
                {editingAssignment?.id === asgn.id && (
                  <div className="mt-4 border-t border-border-default pt-4 space-y-3">
                    <input className="fet-input" value={editingAssignment.title} onChange={(e) => setEditingAssignment({ ...editingAssignment, title: e.target.value })} aria-label="Assignment title" />
                    <textarea className="fet-input min-h-[80px]" value={editingAssignment.description} onChange={(e) => setEditingAssignment({ ...editingAssignment, description: e.target.value })} aria-label="Assignment instructions" />
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <label className="text-xs text-text-secondary">Points
                        <input type="number" min="0" className="fet-input mt-1" value={editingAssignment.points_possible} onChange={(e) => setEditingAssignment({ ...editingAssignment, points_possible: e.target.value })} />
                      </label>
                      <label className="text-xs text-text-secondary">Due date
                        <input type="datetime-local" className="fet-input mt-1" value={toLocalDateTimeInput(editingAssignment.due_at)} onChange={(e) => setEditingAssignment({ ...editingAssignment, due_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
                      </label>
                      <label className="text-xs text-text-secondary">Submission limit (0 = unlimited)
                        <input type="number" min="0" className="fet-input mt-1" value={editingAssignment.max_submissions} onChange={(e) => setEditingAssignment({ ...editingAssignment, max_submissions: e.target.value })} />
                      </label>
                    </div>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editingAssignment.allow_late} onChange={(e) => setEditingAssignment({ ...editingAssignment, allow_late: e.target.checked })} /> Accept late work</label>
                    <div className="flex gap-2 justify-end">
                      <button className="fet-btn-secondary" onClick={() => setEditingAssignment(null)}>Cancel</button>
                      <button className="fet-btn-primary" disabled={savingAssignment} onClick={handleSaveAssignment}>Save changes</button>
                    </div>
                  </div>
                )}
                {!isStaff && asgn.my_submission && (
                  <div className="mt-4 border-t border-border-default pt-3 text-sm">
                    <p className="font-medium text-text-primary">Your latest work: {asgn.my_submission.status.toLowerCase()}</p>
                    {asgn.my_submission.file_info && <a className="text-primary hover:underline" href={learningApi.getDownloadUrl(asgn.my_submission.file_info.id)} target="_blank" rel="noreferrer">{asgn.my_submission.file_info.original_name}</a>}
                    {asgn.my_submission.grade !== null && <p>Grade: {asgn.my_submission.grade}{asgn.points_possible ? ` / ${asgn.points_possible}` : ''}</p>}
                    {asgn.my_submission.feedback && <p className="text-text-secondary">Feedback: {asgn.my_submission.feedback}</p>}
                  </div>
                )}
                {!isStaff && canSubmit && hasTurnedIn && !showSubmitForm && (
                  <button className="mt-3 text-sm text-primary hover:underline" onClick={() => { setSubmitForm({ note: '', file: null }); setActiveSubmitAssignment(asgn.id); }}>Submit another attempt</button>
                )}
                {/* Student turn-in */}
                {!isStaff && canSubmit && showSubmitForm && (
                  <div className="mt-4 border-t border-border-default pt-4">
                    <p className="text-sm font-medium text-text-primary mb-2">
                      {asgn.my_submission?.status === 'RETURNED' ? 'Resubmit your work' : 'Turn in work'}
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <textarea
                        value={submitForm.note}
                        onChange={(e) => setSubmitForm({ ...submitForm, note: e.target.value })}
                        className="fet-input min-h-[60px]"
                        placeholder="Note to your lecturer (optional)"
                      />
                      <input
                        type="file"
                        onChange={(e) => setSubmitForm({ ...submitForm, file: e.target.files[0] })}
                        className="fet-input"
                      />
                    </div>
                    <div className="mt-3 flex justify-end">
                      <button
                        onClick={() => handleSubmitWork(asgn)}
                        disabled={submitting}
                        className="fet-btn-primary flex items-center gap-2"
                      >
                        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload size={16} />}
                        {asgn.my_submission?.status === 'RETURNED' ? 'Resubmit' : 'Turn in'}
                      </button>
                    </div>
                  </div>
                )}
                {!isStaff && !canSubmit && (limitReached ? (
                  <div className="mt-4 border-t border-border-default pt-3 text-sm text-amber-600">
                    Submission limit reached ({used}/{maxSub}). Contact your lecturer if you need to resubmit.
                  </div>
                ) : past && !asgn.allow_late && (
                  <div className="mt-4 border-t border-border-default pt-3 text-sm text-red-600">
                    This assignment is closed (deadline passed).
                  </div>
                ))}

                {/* Staff: submissions */}
                {isStaff && (
                  <div className="mt-4 border-t border-border-default pt-3">
                    <button
                      onClick={() => (expanded ? setExpandedAssignment(null) : loadSubmissions(asgn))}
                      className="flex items-center gap-1.5 text-sm font-medium text-primary"
                    >
                      {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      {expanded ? 'Hide submissions' : `View submissions (${asgn.submissions_count})`}
                    </button>
                    {expanded && (
                      <div className="mt-3">
                        {subsLoading ? (
                          <div className="flex justify-center py-6"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                        ) : subs.length === 0 ? (
                          <p className="text-sm text-text-secondary py-4 text-center">No submissions yet.</p>
                        ) : (
                          <div className="space-y-3">
                            {subs.map((sub) => {
                              const entry = grades[sub.id] || { grade: sub.grade ?? '', feedback: sub.feedback || '' };
                              const subTone = sub.status === 'GRADED' ? 'bg-green-50 text-green-700 border-green-200'
                                : sub.status === 'RETURNED' ? 'bg-amber-50 text-amber-700 border-amber-200'
                                  : sub.is_late ? 'bg-red-50 text-red-700 border-red-200'
                                    : 'bg-blue-50 text-blue-700 border-blue-200';
                              return (
                                <div key={sub.id} className="p-4 rounded-xl border border-border-default bg-page-bg">
                                  <div className="flex items-center justify-between gap-3">
                                    <div>
                                      <p className="font-semibold text-text-primary">{sub.student_name}</p>
                                      <p className="text-xs text-text-secondary">
                                        Turned in {formatDateTime(sub.submitted_at)}
                                        {sub.is_late && <span className="text-red-600"> · late</span>}
                                      </p>
                                      {sub.note && <p className="text-sm text-text-secondary mt-1">{sub.note}</p>}
                                    </div>
                                    <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${subTone}`}>
                                      {sub.status === 'GRADED' ? `Graded (${sub.grade})` : sub.status === 'RETURNED' ? 'Returned' : 'Submitted'}
                                    </span>
                                  </div>
                                  {sub.file_info && (
                                    <a
                                      href={learningApi.getDownloadUrl(sub.file_info.id)}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="mt-2 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
                                    >
                                      <Download size={14} /> {sub.file_info.original_name}
                                    </a>
                                  )}
                                  <div className="mt-3 grid grid-cols-1 md:grid-cols-[140px_1fr_auto] gap-2 items-end">
                                    <label className="flex flex-col gap-1">
                                      <span className="text-xs font-medium text-text-secondary">
                                        Grade{asgn.points_possible ? ` / ${asgn.points_possible}` : ''}
                                      </span>
                                      <input
                                        type="number"
                                        value={entry.grade}
                                        onChange={(e) => setGrades({ ...grades, [sub.id]: { ...entry, grade: e.target.value } })}
                                        className="fet-input"
                                        placeholder="-"
                                      />
                                    </label>
                                    <label className="flex flex-col gap-1">
                                      <span className="text-xs font-medium text-text-secondary">Feedback</span>
                                      <input
                                        type="text"
                                        value={entry.feedback}
                                        onChange={(e) => setGrades({ ...grades, [sub.id]: { ...entry, feedback: e.target.value } })}
                                        className="fet-input"
                                        placeholder="Write a comment…"
                                      />
                                    </label>
                                    <div className="flex gap-2">
                                      <button
                                        onClick={() => handleGrade(sub)}
                                        disabled={savingGrade === sub.id}
                                        className="fet-btn-primary flex items-center gap-1.5 text-sm"
                                      >
                                        {savingGrade === sub.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Award size={14} />}
                                        Save
                                      </button>
                                      <button
                                        onClick={() => handleReturn(asgn, sub)}
                                        className="fet-btn-secondary flex items-center gap-1.5 text-sm"
                                        title="Return for resubmission"
                                      >
                                        <RotateCcw size={14} /> Return
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ---------- MARKS / ASSESSMENTS ---------- */}
      {tab === 'marks' && (
        <AssessmentPanel offeringId={offeringId} user={user} />
      )}
    </div>
  );
};

export default CourseDetail;