/**
 * 登录后始终使用这一套左侧栏。工作空间、创建测试、个人中心只换中间内容，侧栏不卸不换。
 */
import { useState, useEffect, type ReactNode } from 'react';
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { Layout, Menu, Dropdown, Avatar, Typography, message } from 'antd';
import {
  HomeOutlined,
  FormOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  ClockCircleOutlined,
  GlobalOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
  FolderOutlined,
  RobotOutlined,
  ApartmentOutlined,
  ThunderboltOutlined,
  BookOutlined,
  DatabaseOutlined,
  CodeOutlined,
  ApiOutlined,
  MonitorOutlined,
} from '@ant-design/icons';

import LoginPage from './pages/auth/LoginPage';
import RegisterPage from './pages/auth/RegisterPage';
import ForgotPasswordPage from './pages/auth/ForgotPasswordPage';
import AccountHubPage from './pages/product/AccountHubPage';

import TaskListPage from './pages/task/TaskListPage';
import CreateTestPage from './pages/task/CreateTestPage';
import AssetListPage from './pages/asset/AssetListPage';
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

import WorkspacePage from './pages/product/WorkspacePage';
import TeamPage from './pages/product/TeamPage';
import ProjectPage from './pages/product/ProjectPage';
import InvitePage from './pages/product/InvitePage';
import ProjectSwitcher from './pages/product/ProjectSwitcher';
import { getCurrentProjectId } from './pages/product/projectStore';
import './pages/product/product.css';

import { isAuthenticated, getStoredUser, logout, UserInfo } from './services/auth';
import { GlobalErrorBoundary, RouteErrorBoundary } from './components/ErrorBoundary';

const { Sider, Content, Header } = Layout;
const { Text } = Typography;

type MenuItem = NonNullable<Parameters<typeof Menu>[0]['items']>[number];

const menuItems: MenuItem[] = [
  { key: '/workspace', label: '工作空间', icon: <ApartmentOutlined /> },
  { key: '/dashboard', label: '首页', icon: <HomeOutlined /> },
  {
    key: 'nav-task',
    label: '测试任务',
    icon: <FormOutlined />,
    children: [
      { key: '/task', label: '任务列表', icon: <FolderOutlined /> },
      { key: '/task/create', label: '创建测试', icon: <PlusOutlined /> },
    ],
  },
  {
    key: 'nav-asset',
    label: '测试资产',
    icon: <DatabaseOutlined />,
    children: [
      { key: '/asset', label: '用例资产', icon: <FolderOutlined /> },
      { key: '/asset/center', label: '资产中心', icon: <DatabaseOutlined /> },
      { key: '/asset/center/analyze', label: 'AI 分析需求', icon: <RobotOutlined /> },
      { key: '/asset/endpoints', label: '接口管理', icon: <ApiOutlined /> },
      { key: '/asset/pages', label: '页面管理', icon: <GlobalOutlined /> },
      { key: '/asset/scripts', label: '脚本仓库', icon: <CodeOutlined /> },
    ],
  },
  {
    key: 'nav-execution',
    label: '测试执行',
    icon: <PlayCircleOutlined />,
    children: [
      { key: '/execution', label: '执行列表', icon: <PlayCircleOutlined /> },
      { key: '/execution/schedule', label: '定时任务', icon: <ClockCircleOutlined /> },
      { key: '/execution/debug', label: 'AI 接口调试', icon: <RobotOutlined /> },
      { key: '/performance', label: '性能测试', icon: <ThunderboltOutlined /> },
    ],
  },
  { key: '/report', label: '测试报告', icon: <FileTextOutlined /> },
  { key: '/knowledge', label: '知识中心', icon: <BookOutlined /> },
  {
    key: 'nav-system',
    label: '系统管理',
    icon: <SettingOutlined />,
    children: [
      { key: '/system/users', label: '用户管理', icon: <UserOutlined /> },
      { key: '/system/roles', label: '角色权限', icon: <ApartmentOutlined /> },
      { key: '/system/projects', label: '项目管理', icon: <FolderOutlined /> },
      { key: '/system/environments', label: '环境配置', icon: <GlobalOutlined /> },
      { key: '/system/datasources', label: '数据源', icon: <DatabaseOutlined /> },
      { key: '/system/settings', label: '系统设置', icon: <SettingOutlined /> },
      { type: 'divider' },
      { key: '/system/runtime', label: 'Runtime 监控', icon: <MonitorOutlined /> },
      { key: '/system/ai', label: 'AI 能力', icon: <RobotOutlined /> },
    ],
  },
  { type: 'divider' },
  {
    key: 'nav-profile',
    label: '个人中心',
    icon: <UserOutlined />,
    children: [
      { key: '/profile', label: '账号资料' },
      { key: '/profile/ai', label: 'AI 配置' },
      { key: '/profile/env', label: '执行环境' },
      { key: '/profile/security', label: '安全设置' },
    ],
  },
];

const SIDEBAR_OPEN_KEYS = ['nav-task', 'nav-asset', 'nav-execution', 'nav-system', 'nav-profile'];

function getSelectedKeys(pathname: string): string[] {
  if (pathname.startsWith('/workspace')) return ['/workspace'];
  if (pathname.startsWith('/dashboard')) return ['/dashboard'];
  if (pathname.startsWith('/task/create')) return ['/task/create'];
  if (pathname.startsWith('/task/')) return ['/task'];
  if (pathname.startsWith('/task')) return ['/task'];
  if (pathname.startsWith('/asset/center/analyze')) return ['/asset/center/analyze'];
  if (pathname.startsWith('/asset/center')) return ['/asset/center'];
  if (pathname.startsWith('/asset/endpoints')) return ['/asset/endpoints'];
  if (pathname.startsWith('/asset/pages')) return ['/asset/pages'];
  if (pathname.startsWith('/asset/scripts')) return ['/asset/scripts'];
  if (pathname.startsWith('/asset')) return ['/asset'];
  if (pathname.startsWith('/execution/debug')) return ['/execution/debug'];
  if (pathname.startsWith('/execution/schedule')) return ['/execution/schedule'];
  if (pathname.startsWith('/execution/')) return ['/execution'];
  if (pathname.startsWith('/execution')) return ['/execution'];
  if (pathname.startsWith('/performance')) return ['/performance'];
  if (pathname.startsWith('/report')) return ['/report'];
  if (pathname.startsWith('/knowledge')) return ['/knowledge'];
  if (pathname.startsWith('/system/runtime')) return ['/system/runtime'];
  if (pathname.startsWith('/system/ai')) return ['/system/ai'];
  if (pathname.startsWith('/system/users')) return ['/system/users'];
  if (pathname.startsWith('/system/roles')) return ['/system/roles'];
  if (pathname.startsWith('/system/projects')) return ['/system/projects'];
  if (pathname.startsWith('/system/environments')) return ['/system/environments'];
  if (pathname.startsWith('/system/datasources')) return ['/system/datasources'];
  if (pathname.startsWith('/system/settings')) return ['/system/settings'];
  if (pathname.startsWith('/system')) return ['/system'];
  if (pathname.startsWith('/profile/ai')) return ['/profile/ai'];
  if (pathname.startsWith('/profile/env')) return ['/profile/env'];
  if (pathname.startsWith('/profile/security')) return ['/profile/security'];
  if (pathname.startsWith('/profile')) return ['/profile'];
  return ['/dashboard'];
}

function isAuthPage(pathname: string): boolean {
  return pathname.startsWith('/auth');
}

function RequireProject({ children }: { children: ReactNode }) {
  const projectId = getCurrentProjectId();
  if (!projectId) return <Navigate to="/workspace" replace />;
  return <>{children}</>;
}

function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>(SIDEBAR_OPEN_KEYS);
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(getStoredUser());

  useEffect(() => {
    setCurrentUser(getStoredUser());
  }, [location.pathname]);

  const handleLogout = async () => {
    await logout();
    message.success('已退出登录');
    navigate('/auth/login', { replace: true });
  };

  const userMenuItems = [
    { key: 'workspace', icon: <ApartmentOutlined />, label: '工作空间', onClick: () => navigate('/workspace') },
    { key: 'profile', icon: <UserOutlined />, label: '个人中心', onClick: () => navigate('/profile') },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={210}
        style={{ overflow: 'auto', height: '100vh', position: 'fixed', left: 0, top: 0, bottom: 0 }}
      >
        <div style={{ height: 48, margin: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <h1 style={{ color: '#fff', margin: 0, fontSize: collapsed ? '14px' : '16px', whiteSpace: 'nowrap', fontWeight: 700 }}>
            {collapsed ? 'AI' : 'AI 测试平台'}
          </h1>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={getSelectedKeys(location.pathname)}
          openKeys={collapsed ? [] : openKeys}
          items={menuItems}
          onOpenChange={(keys) => {
            if (!collapsed) setOpenKeys(keys);
          }}
          onClick={({ key }) => {
            if (key.startsWith('/')) navigate(key);
          }}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 210, transition: 'margin-left 0.2s' }}>
        <Header style={{
          background: '#fff', padding: '0 24px', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid #f0f0f0', height: 48,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ThunderboltOutlined style={{ color: '#1677ff', fontSize: 18 }} />
            <Text strong>智能自动化测试平台</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <ProjectSwitcher />
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
              <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar size="small" icon={<UserOutlined />} src={currentUser?.avatar} />
                <Text>{currentUser?.display_name || currentUser?.username || '用户'}</Text>
              </div>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ padding: '16px', overflow: 'auto', minHeight: 'calc(100vh - 48px)' }}>
          <RouteErrorBoundary>
            <Routes>
              <Route path="/dashboard" element={<RequireProject><CreateTestPage /></RequireProject>} />
              <Route path="/task" element={<RequireProject><TaskListPage /></RequireProject>} />
              <Route path="/task/create" element={<RequireProject><CreateTestPage /></RequireProject>} />
              <Route path="/task/:id" element={<RequireProject><TaskDetail /></RequireProject>} />
              <Route path="/task/:id/analyze" element={<RequireProject><RequirementAnalyze /></RequireProject>} />
              <Route path="/task/:id/detail" element={<RequireProject><RequirementDetail /></RequireProject>} />
              <Route path="/asset" element={<RequireProject><AssetListPage /></RequireProject>} />
              <Route path="/asset/center" element={<RequireProject><AssetCenterListPage /></RequireProject>} />
              <Route path="/asset/center/new" element={<RequireProject><AssetCenterEditPage /></RequireProject>} />
              <Route path="/asset/center/analyze" element={<RequireProject><AssetCenterAnalyzePage /></RequireProject>} />
              <Route path="/asset/center/:id" element={<RequireProject><AssetCenterDetailPage /></RequireProject>} />
              <Route path="/asset/center/:id/edit" element={<RequireProject><AssetCenterEditPage /></RequireProject>} />
              <Route path="/asset/endpoints" element={<RequireProject><EndpointListPage /></RequireProject>} />
              <Route path="/asset/endpoints/new" element={<RequireProject><EndpointEditPage /></RequireProject>} />
              <Route path="/asset/endpoints/:id" element={<RequireProject><EndpointDetailPage /></RequireProject>} />
              <Route path="/asset/endpoints/:id/edit" element={<RequireProject><EndpointEditPage /></RequireProject>} />
              <Route path="/asset/generate" element={<RequireProject><TestDesignPage /></RequireProject>} />
              <Route path="/asset/draft" element={<RequireProject><TestDesignPage /></RequireProject>} />
              <Route path="/asset/review" element={<RequireProject><TestDesignPage /></RequireProject>} />
              <Route path="/asset/publish" element={<RequireProject><TestDesignPage /></RequireProject>} />
              <Route path="/asset/history" element={<RequireProject><TestDesignPage /></RequireProject>} />
              <Route path="/asset/pages" element={<RequireProject><WebPages /></RequireProject>} />
              <Route path="/asset/scripts" element={<RequireProject><AdminScripts /></RequireProject>} />
              <Route path="/execution" element={<RequireProject><ExecutionListPage /></RequireProject>} />
              <Route path="/execution/recent" element={<RequireProject><ExecutionListPage /></RequireProject>} />
              <Route path="/execution/detail/:id" element={<RequireProject><ExecutionDetailPage /></RequireProject>} />
              <Route path="/execution/api" element={<RequireProject><ExecutionCenterPage /></RequireProject>} />
              <Route path="/execution/web" element={<RequireProject><ExecutionCenterPage /></RequireProject>} />
              <Route path="/execution/schedule" element={<RequireProject><WebSchedule /></RequireProject>} />
              <Route path="/execution/schedule/history" element={<RequireProject><WebScheduleHistory /></RequireProject>} />
              <Route path="/execution/task/:id" element={<RequireProject><WebTaskDetail /></RequireProject>} />
              <Route path="/execution/debug" element={<RequireProject><ApiDebugPage /></RequireProject>} />
              <Route path="/performance" element={<RequireProject><PerformanceListPage /></RequireProject>} />
              <Route path="/performance/:id" element={<RequireProject><PerformanceDetailPage /></RequireProject>} />
              <Route path="/report" element={<RequireProject><ReportListPage /></RequireProject>} />
              <Route path="/report/:id" element={<RequireProject><WebTaskDetail /></RequireProject>} />
              <Route path="/knowledge" element={<RequireProject><KnowledgeCenter /></RequireProject>} />
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
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/workspace/org/:id" element={<TeamPage />} />
              <Route path="/workspace/project/:id" element={<ProjectPage />} />
              <Route path="/workspace/invite/:token" element={<InvitePage />} />
              <Route path="/profile" element={<AccountHubPage />} />
              <Route path="/profile/ai" element={<AccountHubPage />} />
              <Route path="/profile/env" element={<AccountHubPage />} />
              <Route path="/profile/security" element={<AccountHubPage />} />
              <Route path="/" element={<Navigate to="/task/create" replace />} />
              <Route path="/home" element={<Navigate to="/task/create" replace />} />
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
              <Route path="/test" element={<Navigate to="/task/create" replace />} />
              <Route path="/test/*" element={<Navigate to="/task/create" replace />} />
              <Route path="/assets" element={<Navigate to="/asset" replace />} />
            </Routes>
          </RouteErrorBoundary>
        </Content>
      </Layout>
    </Layout>
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
      <MainLayout />
    </GlobalErrorBoundary>
  );
}

export default App;
