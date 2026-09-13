import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { fetchProjectUnderstanding } from '@/services/projectExplorer';
import { ASSET_NAV, FLOW_NAV, appNavOfPath, navGroupOfPath } from './nav';
import { HeaderTools, WorkspaceTopBar } from './ProjectHeaderBar';
import ProjectCreateDrawer from './ProjectCreateDrawer';
import ProjectAgentDock, { PROJECT_CREATE_OPEN } from './ProjectAgentDock';
import './shell.css';

export default function ProjectWorkspaceLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [projectName, setProjectName] = useState(getCurrentProjectName() || '当前项目');
  const [status, setStatus] = useState('empty');
  const [stack, setStack] = useState('');
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [flowOpen, setFlowOpen] = useState(true);
  const [assetOpen, setAssetOpen] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const first = appNavOfPath(location.pathname);
  const selected = navGroupOfPath(location.pathname);
  const inWorkspace = first === 'workspace';

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
      setStack((data?.project?.stack || []).join(' · '));
      setUpdatedAt(data?.updated_at || null);
    }).catch(() => undefined);
  }, [location.pathname, projectName]);

  const go = (path: string) => {
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
              aria-expanded={flowOpen}
              onClick={() => setFlowOpen((open) => !open)}
            >
              <span className="pw-nav-text">项目工作台</span>
              <span className="pw-nav-caret-right">{flowOpen ? '▾' : '▸'}</span>
            </button>
            {flowOpen ? FLOW_NAV.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`pw-nav-l2 ${inWorkspace && selected === item.key ? 'is-on' : ''}`}
                onClick={() => go(item.path)}
              >
                <span className="pw-nav-ico">{item.icon}</span>
                <span className="pw-nav-l2-text">{item.label}</span>
              </button>
            )) : null}

            <button
              type="button"
              className="pw-nav-item pw-nav-first pw-nav-split"
              aria-expanded={assetOpen}
              onClick={() => setAssetOpen((open) => !open)}
            >
              <span className="pw-nav-text">资产</span>
              <span className="pw-nav-caret-right">{assetOpen ? '▾' : '▸'}</span>
            </button>
            {assetOpen ? ASSET_NAV.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`pw-nav-l2 ${inWorkspace && selected === item.key ? 'is-on' : ''}`}
                onClick={() => go(item.path)}
              >
                <span className="pw-nav-ico">{item.icon}</span>
                <span className="pw-nav-l2-text">{item.label}</span>
              </button>
            )) : null}
          </div>
        </nav>
        <main className="pw-main">
          {inWorkspace ? (
            <WorkspaceTopBar
              projectName={projectName}
              status={status}
              stack={stack}
              updatedAt={updatedAt}
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
