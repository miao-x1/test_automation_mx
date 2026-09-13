import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { fetchProjectUnderstanding } from '@/services/projectExplorer';
import { PROJECT_NAV, appNavOfPath, navGroupOfPath } from './nav';
import { HeaderTools, WorkspaceTopBar } from './ProjectHeaderBar';
import ProjectCreateDrawer from './ProjectCreateDrawer';
import ProjectAgentDock, { PROJECT_CREATE_OPEN } from './ProjectAgentDock';
import './shell.css';

export default function ProjectWorkspaceLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [projectName, setProjectName] = useState(getCurrentProjectName() || '当前项目');
  const [status, setStatus] = useState('empty');
  const [workspaceOpen, setWorkspaceOpen] = useState(appNavOfPath(location.pathname) === 'workspace');
  const [createOpen, setCreateOpen] = useState(false);
  const first = appNavOfPath(location.pathname);
  const selected = navGroupOfPath(location.pathname);
  const inWorkspace = first === 'workspace';

  useEffect(() => {
    if (appNavOfPath(location.pathname) === 'workspace') setWorkspaceOpen(true);
    else setWorkspaceOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const openCreate = () => setCreateOpen(true);
    window.addEventListener(PROJECT_CREATE_OPEN, openCreate);
    return () => window.removeEventListener(PROJECT_CREATE_OPEN, openCreate);
  }, []);

  useEffect(() => {
    const sync = () => setProjectName(getCurrentProjectName() || '当前项目');
    sync();
    window.addEventListener(PROJECT_CHANGED, sync);
    return () => window.removeEventListener(PROJECT_CHANGED, sync);
  }, []);

  useEffect(() => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    fetchProjectUnderstanding(projectId).then((data) => {
      setStatus(data?.imported ? (data.status || 'partial') : 'empty');
      if (data?.project?.name) setProjectName(data.project.name);
    }).catch(() => undefined);
  }, [location.pathname, projectName]);

  const toggleWorkspace = () => {
    setWorkspaceOpen((open) => !open);
  };

  const goWorkspaceChild = (path: string) => {
    if (!getCurrentProjectId()) {
      message.info('请先在项目管理中选择一个项目');
      navigate('/projects');
      return;
    }
    navigate(path);
  };

  return (
    <div className="pw">
      <header className="pw-top">
        <span className="pw-brand">
          <span className="pw-mark">◈</span>
          <b>自动化测试平台</b>
        </span>
        <div className="pw-top-right">
          <HeaderTools />
        </div>
      </header>
      <div className="pw-body">
        <nav className="pw-nav">
          <div className="pw-nav-col">
            <button
              type="button"
              className={`pw-nav-item pw-nav-first ${first === 'manage' ? 'is-on' : ''}`}
              onClick={() => navigate('/projects')}
            >
              项目管理
            </button>
            <button
              type="button"
              className="pw-nav-item pw-nav-first pw-nav-split"
              aria-expanded={workspaceOpen}
              aria-label={workspaceOpen ? '收起项目工作台' : '展开项目工作台'}
              onClick={toggleWorkspace}
            >
              <span className="pw-nav-text">项目工作台</span>
              <span className="pw-nav-caret-right" aria-hidden="true">{workspaceOpen ? '▾' : '▸'}</span>
            </button>
            {workspaceOpen ? PROJECT_NAV.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`pw-nav-l2 ${selected === item.key ? 'is-on' : ''}`}
                onClick={() => goWorkspaceChild(item.path)}
              >
                {item.label}
              </button>
            )) : null}
          </div>
        </nav>
        <main className="pw-main">
          {inWorkspace ? (
            <WorkspaceTopBar
              projectName={projectName}
              status={status}
              onCreate={() => setCreateOpen(true)}
            />
          ) : null}
          <div className={`pw-main-body ${first === 'account' ? 'pw-main-pad' : ''}`}>
            <Outlet />
          </div>
        </main>
      </div>
      <ProjectAgentDock />
      <ProjectCreateDrawer
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => setCreateOpen(false)}
      />
    </div>
  );
}
