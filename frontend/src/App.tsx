/**
 * 应用主入口 - 产品级重构
 *
 * 7 个一级导航：
 *   首页 / 测试任务 / 测试资产 / 测试执行 / 测试报告 / 知识中心 / 系统管理
 *
 * 设计理念：
 *   用户只需要输入测试需求，系统自动完成全流程。
 *   Agent / RAG / Graph / Session 等技术概念隐藏在 系统管理 > AI能力 中。
 */
import { useState, useEffect } from 'react';
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

// 认证页面
import LoginPage from './pages/auth/LoginPage';
import RegisterPage from './pages/auth/RegisterPage';
import ProfilePage from './pages/auth/ProfilePage';

// ===== 新页面 =====
import DashboardPage from './pages/dashboard/DashboardPage';
import TaskListPage from './pages/task/TaskListPage';
import CreateTestPage from './pages/task/CreateTestPage';
import AssetListPage from './pages/asset/AssetListPage';
import ExecutionListPage from './pages/execution/ExecutionListPage';
import ExecutionDetailPage from './pages/execution/ExecutionDetailPage';
import ReportListPage from './pages/report/ReportListPage';
import SystemIndexPage from './pages/system/SystemIndexPage';
import AICapabilityPage from './pages/system/AICapabilityPage';

// ===== 复用已有页面 =====
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

// ===== API 接口管理 (新模块) =====
import EndpointListPage from './pages/api-endpoint/EndpointListPage';
import EndpointDetailPage from './pages/api-endpoint/EndpointDetailPage';
import EndpointEditPage from './pages/api-endpoint/EndpointEditPage';

// ===== 测试资产中心 (新模块) =====
import AssetCenterListPage from './pages/asset-center/AssetCenterListPage';
import AssetCenterDetailPage from './pages/asset-center/AssetCenterDetailPage';
import AssetCenterEditPage from './pages/asset-center/AssetCenterEditPage';
import AssetCenterAnalyzePage from './pages/asset-center/AssetCenterAnalyzePage';

// ===== AI 接口调试 (新模块 - Postman + AI 分析) =====
import ApiDebugPage from './pages/api-debug/ApiDebugPage';

// ===== 企业级 Agent Runtime 监控 (新模块) =====
import RuntimeMonitorPage from './pages/runtime-monitor/RuntimeMonitorPage';

// ===== 性能测试 (新模块) =====
import PerformanceListPage from './pages/performance/PerformanceListPage';
import PerformanceDetailPage from './pages/performance/PerformanceDetailPage';

// 认证
import { isAuthenticated, getStoredUser, logout, UserInfo } from './services/auth';

// 错误边界
import { GlobalErrorBoundary, RouteErrorBoundary } from './components/ErrorBoundary';

const { Sider, Content, Header } = Layout;
const { Text } = Typography;

type MenuItem = NonNullable<Parameters<typeof Menu>[0]['items']>[number];

// ===== 新的 7 项一级导航 =====
const menuItems: MenuItem[] = [
  // 1. 首页
  { key: '/dashboard', label: '首页', icon: <HomeOutlined /> },

  // 2. 测试任务
  {
    key: '/task',
    label: '测试任务',
    icon: <FormOutlined />,
    children: [
      { key: '/task', label: '任务列表', icon: <FolderOutlined /> },
      { key: '/task/create', label: '创建测试', icon: <PlusOutlined /> },
    ],
  },

  // 3. 测试资产
  {
    key: '/asset',
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

  // 4. 测试执行
  {
    key: '/execution',
    label: '测试执行',
    icon: <PlayCircleOutlined />,
    children: [
      { key: '/execution', label: '执行列表', icon: <PlayCircleOutlined /> },
      { key: '/execution/schedule', label: '定时任务', icon: <ClockCircleOutlined /> },
      { key: '/execution/debug', label: 'AI 接口调试', icon: <RobotOutlined /> },
      { key: '/performance', label: '性能测试', icon: <ThunderboltOutlined /> },
    ],
  },

  // 5. 测试报告
  { key: '/report', label: '测试报告', icon: <FileTextOutlined /> },

  // 6. 知识中心
  { key: '/knowledge', label: '知识中心', icon: <BookOutlined /> },

  // 7. 系统管理
  {
    key: '/system',
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
  { key: '/profile', label: '个人中心', icon: <UserOutlined /> },
];

function getSelectedKeys(pathname: string): string[] {
  // 首页
  if (pathname.startsWith('/dashboard')) return ['/dashboard'];

  // 测试任务
  if (pathname.startsWith('/task/create')) return ['/task/create'];
  if (pathname.startsWith('/task/')) return ['/task'];
  if (pathname.startsWith('/task')) return ['/task'];

  // 测试资产
  if (pathname.startsWith('/asset/center/analyze')) return ['/asset/center/analyze'];
  if (pathname.startsWith('/asset/center')) return ['/asset/center'];
  if (pathname.startsWith('/asset/endpoints')) return ['/asset/endpoints'];
  if (pathname.startsWith('/asset/pages')) return ['/asset/pages'];
  if (pathname.startsWith('/asset/scripts')) return ['/asset/scripts'];
  if (pathname.startsWith('/asset')) return ['/asset'];

  // 测试执行
  if (pathname.startsWith('/execution/debug')) return ['/execution/debug'];
  if (pathname.startsWith('/execution/schedule')) return ['/execution/schedule'];
  if (pathname.startsWith('/execution/')) return ['/execution'];
  if (pathname.startsWith('/execution')) return ['/execution'];

  // 性能测试
  if (pathname.startsWith('/performance')) return ['/performance'];

  // 测试报告
  if (pathname.startsWith('/report')) return ['/report'];

  // 知识中心
  if (pathname.startsWith('/knowledge')) return ['/knowledge'];

  // 系统管理
  if (pathname.startsWith('/system/runtime')) return ['/system/runtime'];
  if (pathname.startsWith('/system/ai')) return ['/system/ai'];
  if (pathname.startsWith('/system/users')) return ['/system/users'];
  if (pathname.startsWith('/system/roles')) return ['/system/roles'];
  if (pathname.startsWith('/system/projects')) return ['/system/projects'];
  if (pathname.startsWith('/system/environments')) return ['/system/environments'];
  if (pathname.startsWith('/system/datasources')) return ['/system/datasources'];
  if (pathname.startsWith('/system/settings')) return ['/system/settings'];
  if (pathname.startsWith('/system')) return ['/system'];

  if (pathname.startsWith('/profile')) return ['/profile'];
  return ['/dashboard'];
}

function isAuthPage(pathname: string): boolean {
  return pathname.startsWith('/auth');
}

function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
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
          items={menuItems}
          onClick={({ key }) => navigate(key)}
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
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} src={currentUser?.avatar} />
              <Text>{currentUser?.display_name || currentUser?.username || '用户'}</Text>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ padding: '16px', overflow: 'auto', minHeight: 'calc(100vh - 48px)' }}>
          <RouteErrorBoundary>
            <Routes>
              {/* ===== 1. 首页 ===== */}
              <Route path="/dashboard" element={<DashboardPage />} />

              {/* ===== 2. 测试任务 ===== */}
              <Route path="/task" element={<TaskListPage />} />
              <Route path="/task/create" element={<CreateTestPage />} />
              <Route path="/task/:id" element={<TaskDetail />} />
              <Route path="/task/:id/analyze" element={<RequirementAnalyze />} />
              <Route path="/task/:id/detail" element={<RequirementDetail />} />

              {/* ===== 3. 测试资产 ===== */}
              <Route path="/asset" element={<AssetListPage />} />
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

              {/* ===== 4. 测试执行 ===== */}
              <Route path="/execution" element={<ExecutionListPage />} />
              <Route path="/execution/recent" element={<ExecutionListPage />} />
              <Route path="/execution/detail/:id" element={<ExecutionDetailPage />} />
              <Route path="/execution/api" element={<ExecutionCenterPage />} />
              <Route path="/execution/web" element={<ExecutionCenterPage />} />
              <Route path="/execution/schedule" element={<WebSchedule />} />
              <Route path="/execution/schedule/history" element={<WebScheduleHistory />} />
              <Route path="/execution/task/:id" element={<WebTaskDetail />} />
              <Route path="/execution/debug" element={<ApiDebugPage />} />

              {/* ===== 性能测试 ===== */}
              <Route path="/performance" element={<PerformanceListPage />} />
              <Route path="/performance/:id" element={<PerformanceDetailPage />} />

              {/* ===== 5. 测试报告 ===== */}
              <Route path="/report" element={<ReportListPage />} />
              <Route path="/report/:id" element={<WebTaskDetail />} />

              {/* ===== 6. 知识中心 ===== */}
              <Route path="/knowledge" element={<KnowledgeCenter />} />

              {/* ===== 7. 系统管理 ===== */}
              <Route path="/system" element={<SystemIndexPage />} />
              <Route path="/system/users" element={<AdminUsers />} />
              <Route path="/system/roles" element={<AdminRoles />} />
              <Route path="/system/projects" element={<AdminProjects />} />
              <Route path="/system/environments" element={<AdminEnvironments />} />
              <Route path="/system/datasources" element={<AdminDatasources />} />
              <Route path="/system/settings" element={<AdminSettings />} />
              <Route path="/system/settings/general" element={<Settings />} />
              {/* 企业级 Agent Runtime 监控 */}
              <Route path="/system/runtime" element={<RuntimeMonitorPage />} />
              {/* AI 能力（隐藏的技术页面） */}
              <Route path="/system/ai" element={<AICapabilityPage />} />
              <Route path="/system/ai/agent-runtime" element={<AgentRuntimePage />} />
              <Route path="/system/ai/agent-monitor" element={<AgentMonitorPage />} />
              <Route path="/system/ai/sessions" element={<SessionCenterV2 />} />

              {/* ===== 个人中心 ===== */}
              <Route path="/profile" element={<ProfilePage />} />

              {/* ===== 默认 ===== */}
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/home" element={<Navigate to="/dashboard" replace />} />

              {/* ===== 兼容旧路由重定向（保留外部书签/链接可能用到的别名） ===== */}
              {/* /sessions 旧路由 → 新位置 */}
              <Route path="/sessions" element={<Navigate to="/system/ai/sessions" replace />} />
              <Route path="/sessions-v2" element={<Navigate to="/system/ai/sessions" replace />} />

              {/* /admin 旧路由 → /system */}
              <Route path="/admin" element={<Navigate to="/system" replace />} />
              <Route path="/admin/users" element={<Navigate to="/system/users" replace />} />
              <Route path="/admin/roles" element={<Navigate to="/system/roles" replace />} />
              <Route path="/admin/projects" element={<Navigate to="/system/projects" replace />} />
              <Route path="/admin/environments" element={<Navigate to="/system/environments" replace />} />
              <Route path="/admin/datasources" element={<Navigate to="/system/datasources" replace />} />
              <Route path="/admin/settings" element={<Navigate to="/system/settings" replace />} />
              <Route path="/admin/scripts" element={<Navigate to="/asset/scripts" replace />} />
              <Route path="/settings" element={<Navigate to="/system/settings" replace />} />

              {/* 其他旧路由别名 */}
              <Route path="/agent-runtime" element={<Navigate to="/system/ai/agent-runtime" replace />} />
              <Route path="/agent-monitor" element={<Navigate to="/system/ai/agent-monitor" replace />} />
              <Route path="/executions" element={<Navigate to="/execution" replace />} />
              <Route path="/defect" element={<Navigate to="/report" replace />} />
              <Route path="/schedule" element={<Navigate to="/execution/schedule" replace />} />
              <Route path="/schedule-history" element={<Navigate to="/execution/schedule/history" replace />} />
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
