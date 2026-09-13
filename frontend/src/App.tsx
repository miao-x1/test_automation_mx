/**
 * 登录后一级目录：项目管理 / 项目工作台。
 * 工作台内：理解、设计、任务、执行、报告；资产独立。
 */
import { Routes, Route, useLocation, Navigate, Outlet, useParams } from 'react-router-dom';

import LoginPage from './pages/auth/LoginPage';
import RegisterPage from './pages/auth/RegisterPage';
import ForgotPasswordPage from './pages/auth/ForgotPasswordPage';
import AccountHubPage from './pages/product/AccountHubPage';

import TaskListPage from './pages/task/TaskListPage';
import CreateTestPage from './pages/task/CreateTestPage';
import AssetListPage from './pages/asset/AssetListPage';
import AssetLifecyclePage from './pages/asset/AssetLifecyclePage';
import ExecutionListPage from './pages/execution/ExecutionListPage';
import ExecutionDetailPage from './pages/execution/ExecutionDetailPage';
import ReportListPage from './pages/report/ReportListPage';
import SystemIndexPage from './pages/system/SystemIndexPage';
import AICapabilityPage from './pages/system/AICapabilityPage';

import Settings from './pages/settings/Settings';
import TestDesignPage from './pages/test-design/TestDesignPage';
import ExecutionCenterPage from './pages/execution/ExecutionCenterPage';
import WebPages from './pages/web/WebPages';
import WebSchedule from './pages/web/WebSchedule';
import WebScheduleHistory from './pages/web/WebScheduleHistory';
import WebTaskDetail from './pages/web/WebTaskDetail';
import KnowledgeCenter from './pages/knowledge/KnowledgeCenter';
import RequirementAnalyze from './pages/requirement/RequirementAnalyze';
import RequirementDetail from './pages/requirement/RequirementDetail';
import AdminUsers from './pages/admin/AdminUsers';
import AdminRoles from './pages/admin/AdminRoles';
import AdminProjects from './pages/admin/AdminProjects';
import AdminEnvironments from './pages/admin/AdminEnvironments';
import AdminDatasources from './pages/admin/AdminDatasources';
import AdminSettings from './pages/admin/AdminSettings';
import AdminScripts from './pages/admin/AdminScripts';
import AgentRuntimePage from './pages/agent-runtime/AgentRuntimePage';
import AgentMonitorPage from './pages/agent-monitor/AgentMonitorPage';
import SessionCenterV2 from './pages/session/SessionCenterV2';
import TaskDetail from './pages/TaskDetail';

import EndpointListPage from './pages/api-endpoint/EndpointListPage';
import EndpointDetailPage from './pages/api-endpoint/EndpointDetailPage';
import EndpointEditPage from './pages/api-endpoint/EndpointEditPage';

import AssetCenterListPage from './pages/asset-center/AssetCenterListPage';
import AssetCenterDetailPage from './pages/asset-center/AssetCenterDetailPage';
import AssetCenterEditPage from './pages/asset-center/AssetCenterEditPage';
import AssetCenterAnalyzePage from './pages/asset-center/AssetCenterAnalyzePage';

import ApiDebugPage from './pages/api-debug/ApiDebugPage';
import RuntimeMonitorPage from './pages/runtime-monitor/RuntimeMonitorPage';
import PerformanceListPage from './pages/performance/PerformanceListPage';
import PerformanceDetailPage from './pages/performance/PerformanceDetailPage';

import TeamPage from './pages/product/TeamPage';
import ProjectPage from './pages/product/ProjectPage';
import InvitePage from './pages/product/InvitePage';
import UnderstandLayout from './pages/understand/UnderstandLayout';
import RequirementAnalysisPage from './pages/understand/RequirementAnalysisPage';
import {
  ApisSection,
  CodeSection,
  CoverageSection,
  FeaturesSection,
  FlowsSection,
  ModulesSection,
  OverviewSection,
  PagesSection,
} from './pages/understand/UnderstandViews';
import { AgentSection } from './pages/understand/UnderstandAgent';
import TestTaskWorkbenchPage from './pages/product/TestTaskWorkbenchPage';
import CaseWorkbenchPage from './pages/shell/CaseWorkbenchPage';
import { getCurrentProjectId, setCurrentProjectId } from './pages/product/projectStore';
import { fetchWorkspace } from './services/workspace';
import ProjectWorkspaceLayout from './pages/shell/ProjectWorkspaceLayout';
import ProjectCenterPage from './pages/shell/ProjectCenterPage';
import DesignStudioPage from './pages/shell/DesignStudioPage';
import { DefectPage, RegressionPage, TestPrepPage, TestReportPage, TestRunPage, VerifyPage } from './pages/pipeline/pipelinePages';
import './pages/product/product.css';

import { isAuthenticated } from './services/auth';
import { GlobalErrorBoundary, RouteErrorBoundary } from './components/ErrorBoundary';

function TestTaskWorkbenchRoute() {
  return <TestTaskWorkbenchPage />;
}

function isAuthPage(pathname: string): boolean {
  return pathname.startsWith('/auth');
}

function RequireProject() {
  const projectId = getCurrentProjectId();
  if (!projectId) return <Navigate to="/projects" replace />;
  return <Outlet />;
}

const PROJECT_WORKSPACE_ALIAS: Record<string, string> = {
  '': '/understand',
  '/': '/understand',
  '/overview': '/understand',
  '/understanding': '/understand',
  '/design': '/design',
  '/tasks': '/test-tasks',
  '/execution': '/execute',
  '/reports': '/report',
  '/prepare': '/prepare',
  '/defects': '/defects',
  '/verify': '/verify',
  '/regression': '/regression',
};

function aliasWorkspacePath(suffix: string) {
  if (PROJECT_WORKSPACE_ALIAS[suffix]) return PROJECT_WORKSPACE_ALIAS[suffix];
  const rules: Array<[string, string]> = [
    ['/understanding', '/understand'],
    ['/design', '/design'],
    ['/tasks', '/test-tasks'],
    ['/execution', '/execute'],
    ['/reports', '/report'],
    ['/overview', '/understand'],
  ];
  for (const [from, to] of rules) {
    if (suffix === from || suffix.startsWith(`${from}/`)) return `${to}${suffix.slice(from.length)}`;
  }
  return '/understand';
}

function BindProjectWorkspace() {
  const { projectId } = useParams();
  const location = useLocation();
  const id = Number(projectId);
  if (!Number.isFinite(id) || id <= 0) return <Navigate to="/projects" replace />;
  if (getCurrentProjectId() !== id) {
    setCurrentProjectId(id);
    fetchWorkspace().then((data) => {
      const row = (data?.projects || []).find((item: { id: number }) => item.id === id);
      if (row?.name) setCurrentProjectId(id, row.name);
    }).catch(() => undefined);
  }
  const suffix = location.pathname.replace(/^\/project\/\d+\/workspace/, '') || '/';
  return <Navigate to={aliasWorkspacePath(suffix)} replace />;
}

function AppRoutes() {
  return (
    <RouteErrorBoundary>
      <Routes>
        <Route element={<ProjectWorkspaceLayout />}>
          <Route path="/projects" element={<ProjectCenterPage />} />
          <Route path="/workspace/org/:id" element={<TeamPage />} />
          <Route path="/workspace/project/:id" element={<ProjectPage />} />
          <Route path="/workspace/invite/:token" element={<InvitePage />} />
          <Route path="/profile" element={<AccountHubPage />} />
          <Route path="/profile/platform" element={<AccountHubPage />} />
          <Route path="/profile/ai" element={<AccountHubPage />} />
          <Route path="/profile/env" element={<AccountHubPage />} />
          <Route path="/profile/security" element={<AccountHubPage />} />
          <Route path="/system" element={<SystemIndexPage />} />
          <Route path="/system/users" element={<AdminUsers />} />
          <Route path="/system/roles" element={<AdminRoles />} />
          <Route path="/system/projects" element={<AdminProjects />} />
          <Route path="/system/environments" element={<AdminEnvironments />} />
          <Route path="/system/datasources" element={<AdminDatasources />} />
          <Route path="/system/settings" element={<AdminSettings />} />
          <Route path="/system/settings/general" element={<Settings />} />
          <Route path="/system/runtime" element={<RuntimeMonitorPage />} />
          <Route path="/system/ai" element={<AICapabilityPage />} />
          <Route path="/system/ai/agent-runtime" element={<AgentRuntimePage />} />
          <Route path="/system/ai/agent-monitor" element={<AgentMonitorPage />} />
          <Route path="/system/ai/sessions" element={<SessionCenterV2 />} />
          <Route path="/project/:projectId/workspace/*" element={<BindProjectWorkspace />} />
          <Route element={<RequireProject />}>
          <Route path="/knowledge" element={<KnowledgeCenter />} />
          <Route path="/workbench" element={<Navigate to="/understand" replace />} />
          <Route path="/understand/requirements" element={<RequirementAnalysisPage />} />
          <Route path="/understand" element={<UnderstandLayout />}>
            <Route index element={<OverviewSection />} />
            <Route path="pages" element={<PagesSection />} />
            <Route path="features" element={<FeaturesSection />} />
            <Route path="modules" element={<ModulesSection />} />
            <Route path="apis" element={<ApisSection />} />
            <Route path="code" element={<CodeSection />} />
            <Route path="flows" element={<FlowsSection />} />
            <Route path="coverage" element={<CoverageSection />} />
            <Route path="agent" element={<AgentSection />} />
          </Route>
          <Route path="/design" element={<DesignStudioPage />} />
          <Route path="/design/:section" element={<DesignStudioPage />} />
          <Route path="/test-tasks" element={<CaseWorkbenchPage />} />
          <Route path="/test-tasks/:id" element={<TestTaskWorkbenchRoute />} />
          <Route path="/prepare" element={<TestPrepPage />} />
          <Route path="/execute" element={<TestRunPage />} />
          <Route path="/defects" element={<DefectPage />} />
          <Route path="/verify" element={<VerifyPage />} />
          <Route path="/regression" element={<RegressionPage />} />
          <Route path="/report" element={<TestReportPage />} />
          <Route path="/task" element={<TaskListPage />} />
          <Route path="/task/create" element={<CreateTestPage />} />
          <Route path="/task/:id" element={<TaskDetail />} />
          <Route path="/task/:id/analyze" element={<RequirementAnalyze />} />
          <Route path="/task/:id/detail" element={<RequirementDetail />} />
          <Route path="/asset" element={<Navigate to="/asset/lifecycle" replace />} />
          <Route path="/asset/legacy" element={<AssetListPage />} />
          <Route path="/asset/lifecycle" element={<AssetLifecyclePage />} />
          <Route path="/asset/lifecycle/:stage" element={<AssetLifecyclePage />} />
          <Route path="/asset/center" element={<AssetCenterListPage />} />
          <Route path="/asset/center/new" element={<AssetCenterEditPage />} />
          <Route path="/asset/center/analyze" element={<AssetCenterAnalyzePage />} />
          <Route path="/asset/center/:id" element={<AssetCenterDetailPage />} />
          <Route path="/asset/center/:id/edit" element={<AssetCenterEditPage />} />
          <Route path="/asset/endpoints" element={<EndpointListPage />} />
          <Route path="/asset/endpoints/new" element={<EndpointEditPage />} />
          <Route path="/asset/endpoints/:id" element={<EndpointDetailPage />} />
          <Route path="/asset/endpoints/:id/edit" element={<EndpointEditPage />} />
          <Route path="/asset/generate" element={<TestDesignPage />} />
          <Route path="/asset/draft" element={<TestDesignPage />} />
          <Route path="/asset/review" element={<TestDesignPage />} />
          <Route path="/asset/publish" element={<TestDesignPage />} />
          <Route path="/asset/history" element={<TestDesignPage />} />
          <Route path="/asset/pages" element={<WebPages />} />
          <Route path="/asset/scripts" element={<AdminScripts />} />
          <Route path="/execution" element={<ExecutionListPage />} />
          <Route path="/execution/recent" element={<ExecutionListPage />} />
          <Route path="/execution/detail/:id" element={<ExecutionDetailPage />} />
          <Route path="/execution/api" element={<ExecutionCenterPage />} />
          <Route path="/execution/web" element={<ExecutionCenterPage />} />
          <Route path="/execution/schedule" element={<WebSchedule />} />
          <Route path="/execution/schedule/history" element={<WebScheduleHistory />} />
          <Route path="/execution/task/:id" element={<WebTaskDetail />} />
          <Route path="/execution/debug" element={<ApiDebugPage />} />
          <Route path="/performance" element={<PerformanceListPage />} />
          <Route path="/performance/:id" element={<PerformanceDetailPage />} />
          <Route path="/report/:id" element={<WebTaskDetail />} />
          </Route>
        </Route>

        <Route path="/workspace" element={<Navigate to="/projects" replace />} />
        <Route path="/dashboard" element={<Navigate to="/understand" replace />} />
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/home" element={<Navigate to="/projects" replace />} />
        <Route path="/account" element={<Navigate to="/profile" replace />} />
        <Route path="/sessions" element={<Navigate to="/system/ai/sessions" replace />} />
        <Route path="/sessions-v2" element={<Navigate to="/system/ai/sessions" replace />} />
        <Route path="/admin" element={<Navigate to="/system" replace />} />
        <Route path="/admin/users" element={<Navigate to="/system/users" replace />} />
        <Route path="/admin/roles" element={<Navigate to="/system/roles" replace />} />
        <Route path="/admin/projects" element={<Navigate to="/system/projects" replace />} />
        <Route path="/admin/environments" element={<Navigate to="/system/environments" replace />} />
        <Route path="/admin/datasources" element={<Navigate to="/system/datasources" replace />} />
        <Route path="/admin/settings" element={<Navigate to="/system/settings" replace />} />
        <Route path="/admin/scripts" element={<Navigate to="/asset/scripts" replace />} />
        <Route path="/settings" element={<Navigate to="/system/settings" replace />} />
        <Route path="/agent-runtime" element={<Navigate to="/system/ai/agent-runtime" replace />} />
        <Route path="/agent-monitor" element={<Navigate to="/system/ai/agent-monitor" replace />} />
        <Route path="/executions" element={<Navigate to="/execution" replace />} />
        <Route path="/defect" element={<Navigate to="/report" replace />} />
        <Route path="/schedule" element={<Navigate to="/execution/schedule" replace />} />
        <Route path="/schedule-history" element={<Navigate to="/execution/schedule/history" replace />} />
        <Route path="/test" element={<Navigate to="/projects" replace />} />
        <Route path="/test/*" element={<Navigate to="/projects" replace />} />
        <Route path="/assets" element={<Navigate to="/asset" replace />} />
      </Routes>
    </RouteErrorBoundary>
  );
}

function App() {
  const location = useLocation();
  const authenticated = isAuthenticated();

  if (isAuthPage(location.pathname)) {
    return (
      <GlobalErrorBoundary>
        <Routes>
          <Route path="/auth/login" element={<LoginPage />} />
          <Route path="/auth/register" element={<RegisterPage />} />
          <Route path="/auth/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/auth/*" element={<Navigate to="/auth/login" replace />} />
        </Routes>
      </GlobalErrorBoundary>
    );
  }

  if (!authenticated) {
    return <Navigate to="/auth/login" replace />;
  }

  return (
    <GlobalErrorBoundary>
      <AppRoutes />
    </GlobalErrorBoundary>
  );
}

export default App;
