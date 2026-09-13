import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Avatar, Dropdown, Input, Popover, message } from 'antd';
import { getStoredUser, logout, type UserInfo } from '@/services/auth';
import { fetchWorkspace, type Project } from '@/services/workspace';
import { getCurrentProjectId, setCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { openProjectAgent } from '@/services/projectExplorer';

export function UserMenu() {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserInfo | null>(getStoredUser());

  useEffect(() => {
    setUser(getStoredUser());
  }, []);

  return (
    <Dropdown
      menu={{
        items: [
          { key: 'profile', label: '个人中心', onClick: () => navigate('/profile') },
          { key: 'system', label: '系统管理', onClick: () => navigate('/system') },
          { key: 'logout', label: '退出登录', onClick: async () => {
            await logout();
            message.success('已退出登录');
            navigate('/auth/login', { replace: true });
          } },
        ],
      }}
    >
      <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Avatar size="small" src={user?.avatar}>{user?.display_name?.[0] || user?.username?.[0] || '用'}</Avatar>
        <span>{user?.display_name || user?.username || '用户'}</span>
      </div>
    </Dropdown>
  );
}

export function ProjectSwitcherMenu({ onCreate }: { onCreate: () => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [keyword, setKeyword] = useState('');
  const [currentId, setCurrentId] = useState(getCurrentProjectId());

  const load = () => {
    fetchWorkspace().then((data) => setProjects(data?.projects || [])).catch(() => undefined);
    setCurrentId(getCurrentProjectId());
  };

  useEffect(() => {
    load();
    const sync = () => load();
    window.addEventListener(PROJECT_CHANGED, sync);
    return () => window.removeEventListener(PROJECT_CHANGED, sync);
  }, []);

  const rows = projects.filter((item) => !keyword.trim() || item.name.toLowerCase().includes(keyword.trim().toLowerCase()));

  return (
    <div className="pw-switcher">
      <Input allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索项目" style={{ marginBottom: 8 }} />
      <div className="pw-switcher-list">
        <div className="pw-nav-label">最近项目</div>
        {rows.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`pw-switcher-row ${item.id === currentId ? 'is-on' : ''}`}
            onClick={() => {
              setCurrentProjectId(item.id, item.name);
            }}
          >
            <span className="pw-mark">{item.name.slice(0, 1)}</span>
            <span>{item.id === currentId ? '✓ ' : ''}{item.name}</span>
          </button>
        ))}
      </div>
      <div className="pw-switcher-foot">
        <button type="button" className="pw-switcher-row" onClick={onCreate}>＋ 新建项目</button>
      </div>
    </div>
  );
}

export function WorkspaceTopBar({
  projectName,
  status,
  onCreate,
}: {
  projectName: string;
  status: string;
  onCreate: () => void;
}) {
  return (
    <div className="pw-workspace-top">
      <div className="pw-workspace-left">
        <Popover trigger="click" placement="bottomLeft" content={<ProjectSwitcherMenu onCreate={onCreate} />}>
          <button type="button" className="pw-switch">
            <span className="pw-mark">{(projectName || 'P').slice(0, 1)}</span>
            <b>{projectName || '当前项目'}</b>
            <span>▼</span>
          </button>
        </Popover>
        <span className="pw-workspace-status">
          <i className={`pw-dot ${status === 'ready' ? 'ok' : status === 'empty' ? '' : 'warn'}`} />
          {status === 'ready' ? '项目正常' : status === 'empty' ? '尚未分析' : '部分完成'}
        </span>
      </div>
      <button
        type="button"
        className="pw-agent-btn"
        onClick={() => openProjectAgent()}
        aria-label={`AI 测试助手，当前项目 ${projectName || '当前项目'}`}
      >
        AI 测试助手
      </button>
    </div>
  );
}

export function HeaderTools() {
  return (
    <>
      <Popover content="通知会来自当前项目的执行失败和任务状态。现在没有独立通知服务。" trigger="click">
        <button className="pw-icon-btn" type="button" aria-label="通知">通知</button>
      </Popover>
      <Popover content="项目是容器。项目理解、测试设计、测试任务、测试执行、知识是项目内工作区。agent助手对应选中的项目。" trigger="click">
        <button className="pw-icon-btn" type="button" aria-label="帮助">帮助</button>
      </Popover>
      <UserMenu />
    </>
  );
}
