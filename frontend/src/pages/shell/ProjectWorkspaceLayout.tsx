import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { fetchProjectUnderstanding, openProjectAgent } from '@/services/projectExplorer';
import { PROJECT_NAV, appNavOfPath, navGroupOfPath } from './nav';
import { HeaderTools, WorkspaceTopBar } from './ProjectHeaderBar';
import ProjectCreateDrawer from './ProjectCreateDrawer';
import ProjectAgentDock from './ProjectAgentDock';
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

  const goWorkbench = () => {
    if (!getCurrentProjectId()) {
      message.info('请先在项目管理中选择一个项目');
      navigate('/projects');
      return;
    }
    setWorkspaceOpen(true);
    navigate('/workbench');
  };

  return (
    <div className="pw">
      <header className="pw-top">
        <span className="pw-brand">
          <span className="pw-mark">◈</span>
          <b>自动化测试平台</b>
        </span>
        <div className="pw-top-right">
          <button type="button" className="pw-agent-btn" onClick={() => openProjectAgent()} aria-label="AI 项目助手">
            ✦ 助手
          </button>
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
            <div className={`pw-nav-item pw-nav-first pw-nav-split ${first === 'workspace' && selected === 'workbench' ? 'is-on' : ''}`}>
              <button type="button" className="pw-nav-text" onClick={goWorkbench}>项目工作台</button>
              <button
                type="button"
                className="pw-nav-caret-right"
                aria-label={workspaceOpen ? '收起项目工作台' : '展开项目工作台'}
                onClick={() => {
                  if (!getCurrentProjectId()) {
                    message.info('请先在项目管理中选择一个项目');
                    navigate('/projects');
                    return;
                  }
                  if (workspaceOpen) setWorkspaceOpen(false);
                  else {
                    setWorkspaceOpen(true);
                    if (!inWorkspace) navigate('/workbench');
                  }
                }}
              >
                {workspaceOpen ? '▾' : '▸'}
              </button>
            </div>
            {workspaceOpen ? PROJECT_NAV.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`pw-nav-l2 ${selected === item.key ? 'is-on' : ''}`}
                onClick={() => navigate(item.path)}
              >
                {item.label}
              </button>
            )) : null}
            <button
              type="button"
              className={`pw-nav-item pw-nav-first ${first === 'knowledge' ? 'is-on' : ''}`}
              onClick={() => navigate('/knowledge')}
            >
              知识
            </button>
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
          <div className="pw-main-body">
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
