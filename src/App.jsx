import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import Sidebar from './components/Layout/Sidebar';
import Header from './components/Layout/Header';
import ScrollManager from './components/Layout/ScrollManager';
import DashboardHome from './components/Dashboard/DashboardHome';
import StudentDashboard from './components/Dashboard/StudentDashboard';
import LecturerDashboard from './components/Dashboard/LecturerDashboard';
import CoordinatorDashboard from './components/Dashboard/CoordinatorDashboard';
import Login from './components/Auth/Login';
import SignUp from './components/Auth/SignUp';
import ForgotPassword from './components/Auth/ForgotPassword';
import OtpVerification from './components/Auth/OtpVerification';
import ResetPassword from './components/Auth/ResetPassword';
import ChangePassword from './components/Auth/ChangePassword';
import ProfilePage from './components/Profile/ProfilePage';
import AttendanceDashboard from './components/Attendance/AttendanceDashboard';
import ProjectsList from './components/Projects/ProjectsList';
import ProjectDetails from './components/Projects/ProjectDetails';
import ContinuousAssessment from './components/Assessment/ContinuousAssessment';
import ContributionTracking from './components/Assessment/ContributionTracking';
import AnnouncementList from './components/Announcements/AnnouncementList';
import AcademicCalendar from './components/Academic/AcademicCalender';
import AcademicSetup from './components/Academic/AcademicSetup';
import Timetable from './components/Academic/Timetable';
import CarryOverPage from './components/Academic/CarryOverPage';
import NotificationList from './components/Notifications/NotificationList';
import RosterUpload from './components/Admin/RosterUpload';
import RegistrationPage from './Pages/Courses/RegistrationPage';
import AdminDashboard from './Pages/Admin/AdminDashboard';
import AdminUsers from './Pages/Admin/Users';
import MobileSimulator from './components/Mobile/MobileSimulator';
import MyCourses from './Pages/Lessons/MyCourses';
import CourseDetail from './Pages/Lessons/CourseDetail';
import { authApi } from './lib/auth';
import { normalizeRole } from './lib/profile';

const RequireRole = ({ role, children }) => {
  let userRole = 'student';
  try {
    const stored = localStorage.getItem('fet_user');
    const user = stored ? JSON.parse(stored) : null;
    userRole = user?.role || localStorage.getItem('fet_user_role') || 'student';
  } catch {
    userRole = localStorage.getItem('fet_user_role') || 'student';
  }

  if (normalizeRole(userRole) !== normalizeRole(role)) {
    return <Navigate to="/" replace />;
  }
  return children;
};

const ExcludeRole = ({ role, children }) => {
  let userRole = 'student';
  try {
    const stored = localStorage.getItem('fet_user');
    const user = stored ? JSON.parse(stored) : null;
    userRole = user?.role || localStorage.getItem('fet_user_role') || 'student';
  } catch {
    userRole = localStorage.getItem('fet_user_role') || 'student';
  }

  if (normalizeRole(userRole) === normalizeRole(role)) {
    return <Navigate to="/lessons" replace />;
  }
  return children;
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [showSignUp, setShowSignUp] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  // Which unauthenticated screen to show. Seeded from the URL so a direct visit
  // to /forgot-password or /verify-otp lands on the right screen.
  const [authScreen, setAuthScreen] = useState(() => {
    const path = window.location.pathname;
    if (path.startsWith('/verify-otp')) return 'otp';
    if (path.startsWith('/reset-password')) return 'reset';
    if (path.startsWith('/forgot-password')) return 'forgot';
    return 'login';
  });
  const [resetEmail, setResetEmail] = useState(
    () => new URLSearchParams(window.location.search).get('email') || '',
  );
  // The verified OTP is kept in memory only (never in the URL) and is consumed
  // by the final "set a new password" step.
  const [resetOtp, setResetOtp] = useState('');

  useEffect(() => {
    const initAuth = async () => {
      try {
        // Session is validated against the backend using httpOnly cookies.
        const response = await authApi.me();
        const userData = response.data?.data ?? response.data;
        setUser(userData);
        setIsAuthenticated(true);
        // Update cached user snapshot
        localStorage.setItem('fet_auth', 'true');
        localStorage.setItem('fet_user', JSON.stringify(userData));
        localStorage.setItem('fet_user_role', userData.role || 'student');
        localStorage.setItem('fet_user_name', userData.fullName || userData.email?.split('@')[0] || 'User');
      } catch (error) {
        // No valid session (or refresh failed) — clear cache, show login.
        localStorage.removeItem('fet_auth');
        localStorage.removeItem('fet_user');
        localStorage.removeItem('fet_user_role');
        localStorage.removeItem('fet_user_name');
      }
      setIsLoading(false);
    };
    initAuth();
  }, []);

  useEffect(() => {
    const onProfileUpdate = () => {
      try {
        const u = JSON.parse(localStorage.getItem('fet_user') || '{}');
        if (u && u.fullName) setUser(u);
      } catch { /* ignore */ }
    };
    const onSessionExpired = () => {
      // The axios interceptor refresh could not recover the session. Drop to
      // the login screen in-place; no reload, no redirect loop.
      setIsAuthenticated(false);
      setUser(null);
    };
    window.addEventListener('fet-profile-updated', onProfileUpdate);
    window.addEventListener('fet:session-expired', onSessionExpired);
    return () => {
      window.removeEventListener('fet-profile-updated', onProfileUpdate);
      window.removeEventListener('fet:session-expired', onSessionExpired);
    };
  }, []);

  const handleLogin = (userData) => {
    setIsAuthenticated(true);
    setUser(userData);
    localStorage.setItem('fet_auth', 'true');
    localStorage.setItem('fet_user', JSON.stringify(userData));
    localStorage.setItem('fet_user_role', userData.role || 'student');
    localStorage.setItem('fet_user_name', userData.fullName || userData.email?.split('@')[0] || 'User');
  };

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setIsAuthenticated(false);
      setUser(null);
      localStorage.removeItem('fet_auth');
      localStorage.removeItem('fet_user');
      localStorage.removeItem('fet_user_role');
      localStorage.removeItem('fet_user_name');
      localStorage.removeItem('access_token');
    }
  };

  const handleSwitchToSignUp = () => setShowSignUp(true);
  const handleSwitchToLogin = () => setShowSignUp(false);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-page-bg">
        <div className="text-center">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-4" style={{ backgroundColor: '#3F35B5' }}>
            <span className="text-white font-bold text-lg">FET</span>
          </div>
          <div className="w-8 h-8 border-[3px] border-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="mt-3 text-[13px] text-text-secondary font-medium">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    if (authScreen === 'otp') {
      return (
        <OtpVerification
          email={resetEmail}
          onVerified={(code) => {
            setResetOtp(code);
            setAuthScreen('reset');
          }}
          onBack={() => {
            setResetOtp('');
            window.history.replaceState({}, '', '/forgot-password');
            setAuthScreen('forgot');
          }}
        />
      );
    }
    if (authScreen === 'reset') {
      return (
        <ResetPassword
          email={resetEmail}
          otp={resetOtp}
          onBack={() => setAuthScreen('otp')}
          onDone={() => {
            // Drop the email from the address bar.
            window.history.replaceState({}, '', '/');
            setResetEmail('');
            setResetOtp('');
            setAuthScreen('login');
          }}
        />
      );
    }
    if (authScreen === 'forgot') {
      return (
        <ForgotPassword
          onBack={() => setAuthScreen('login')}
          onCodeSent={(email) => {
            setResetEmail(email);
            window.history.replaceState({}, '', `/verify-otp?email=${encodeURIComponent(email)}`);
            setAuthScreen('otp');
          }}
        />
      );
    }
    if (showSignUp) {
      return <SignUp onSignUp={handleLogin} onSwitchToLogin={handleSwitchToLogin} />;
    }
    return (
      <Login
        onLogin={handleLogin}
        onSwitchToSignUp={handleSwitchToSignUp}
        onForgotPassword={() => setAuthScreen('forgot')}
      />
    );
  }

  const userName = user?.fullName || user?.email?.split('@')[0] || 'User';
  const userRole = user?.role || 'student';

  // BR-003: a roster-created account signs in with a temporary password and
  // stays locked out of everything else until it is replaced. The flag comes
  // from /auth/me/, so this is the client's view of a server-enforced rule.
  const mustChangePassword = Boolean(user?.must_change_password);

  return (
    <ThemeProvider>
      <Router>
          <ScrollManager />
          <div className="app-container flex h-screen bg-page-bg">
            <Sidebar onLogout={handleLogout} userName={userName} userRole={userRole} />
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <Header user={user} onLogout={handleLogout} />
              <main className="app-scroll flex-1 overflow-y-auto p-4 md:p-6">
                <Routes>
                  <Route path="/" element={<DashboardHome />} />
                  <Route path="/dashboard" element={<DashboardHome />} />
                  <Route path="/student-dashboard" element={<StudentDashboard user={user} />} />
                  <Route path="/lecturer-dashboard" element={<LecturerDashboard user={user} />} />
                  <Route path="/coordinator-dashboard" element={<CoordinatorDashboard user={user} />} />
                  <Route path="/profile" element={<ProfilePage user={user} />} />
                  <Route path="/lessons" element={<MyCourses user={user} />} />
                  <Route path="/lessons/:offeringId" element={<CourseDetail user={user} />} />
                  <Route path="/attendance" element={<AttendanceDashboard user={user} />} />
                <Route path="/projects" element={<ProjectsList />} />
                <Route path="/projects/:id" element={<ProjectDetails />} />
                <Route path="/assessment" element={<ContinuousAssessment user={user} />} />
                <Route
                  path="/contribution/tracking"
                  element={<RequireRole role="lecturer"><ContributionTracking user={user} /></RequireRole>}
                />
                <Route path="/announcements" element={<AnnouncementList user={user} />} />
                <Route path="/notifications" element={<NotificationList />} />
                <Route path="/timetable" element={<Timetable />} />
                <Route path="/carry-over" element={<CarryOverPage user={user} />} />
                <Route
                  path="/register"
                  element={<RequireRole role="student"><RegistrationPage /></RequireRole>}
                />
                <Route path="/academic" element={<AcademicCalendar />} />
                <Route path="/mobile-simulator" element={<MobileSimulator />} />
                <Route path="/settings" element={<ProfilePage user={user} />} />
                <Route
                  path="/admin/dashboard"
                  element={<RequireRole role="admin"><AdminDashboard user={user} /></RequireRole>}
                />
                <Route
                  path="/admin/academic"
                  element={<RequireRole role="admin"><AcademicSetup /></RequireRole>}
                />
                <Route
                  path="/admin/roster"
                  element={<RequireRole role="admin"><RosterUpload /></RequireRole>}
                />
                <Route
                  path="/change-password"
                  element={<ChangePassword user={user} forced={mustChangePassword} />}
                />
                {/* Mock pages removed. Their live equivalents already exist, so
                    old links land somewhere real instead of the catch-all. */}
                <Route path="/tasks" element={<Navigate to="/projects" replace />} />
                <Route path="/groups" element={<Navigate to="/projects" replace />} />
                <Route path="/contribution" element={<Navigate to="/projects" replace />} />
                <Route path="/courses" element={<Navigate to="/lessons" replace />} />
                <Route
                  path="/admin/users"
                  element={<RequireRole role="admin"><AdminUsers user={user} /></RequireRole>}
                />
                <Route
                  path="*"
                  element={mustChangePassword
                    ? <Navigate to="/change-password" replace />
                    : <Navigate to="/" />}
                />
                </Routes>
              </main>
            </div>
          </div>
        </Router>
    </ThemeProvider>
  );
}

export default App;
