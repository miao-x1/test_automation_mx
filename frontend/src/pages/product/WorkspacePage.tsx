import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Empty, Form, Input, Modal, Tag, message } from 'antd';
import {
  createOrganization,
  createProject,
  fetchWorkspace,
  type Organization,
  type Project,
} from '@/services/workspace';
import { getCurrentProjectId, setCurrentProjectId, resolveProjectId } from './projectStore';
import { WORKSPACE_LINKS } from './pillarNav';
import './product.css';

const STATUS_TEXT: Record<string, { color: string; text: string }> = {
  SUCCESS: { color: 'green', text: '通过' },
  FAILED: { color: 'red', text: '失败' },
  UNSTABLE: { color: 'orange', text: '不稳定' },
  RUNNING: { color: 'blue', text: '执行中' },
  IDLE: { color: 'default', text: '尚未测试' },
};

const ROLE_TEXT: Record<string, string> = {
  OWNER: 'Owner',
  ADMIN: 'Admin',
  MEMBER: 'Member',
};

function TeamTile({ org }: { org: Organization }) {
  return (
    <Link to={`/workspace/org/${org.id}`} className="product-tile">
      <div className="product-tile-head">
        {org.avatar ? <img className="product-avatar" src={org.avatar} alt="" /> : <span className="product-avatar product-avatar-fallback">{(org.name || '团').slice(0, 1)}</span>}
        <strong>{org.name}</strong>
      </div>
      <span>{org.member_count ?? 0} 名成员 · {org.project_count ?? 0} 个项目</span>
      <em>我的角色：{ROLE_TEXT[org.my_role || ''] || org.my_role || '-'}</em>
    </Link>
  );
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [recentActivity, setRecentActivity] = useState<any[]>([]);
  const [recentJobs, setRecentJobs] = useState<any[]>([]);
  const [recentFailures, setRecentFailures] = useState<any[]>([]);
  const [teamOpen, setTeamOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [teamForm] = Form.useForm();
  const [projectForm] = Form.useForm();

  const personal = orgs.filter((org) => org.is_personal);
  const teams = orgs.filter((org) => !org.is_personal);
  const currentProject = projects.find((item) => item.id === getCurrentProjectId()) || projects[0];

  const load = async () => {
    const data = await fetchWorkspace();
    setOrgs(data?.organizations || []);
    setProjects(data?.projects || []);
    setRecentActivity(data?.recent_activity || []);
    setRecentJobs(data?.recent_jobs || []);
    setRecentFailures(data?.recent_failures || []);
    if (data?.default_project_id && !sessionStorage.getItem('current_project_id')) {
      setCurrentProjectId(data.default_project_id);
    }
  };

  useEffect(() => {
    load().catch(() => message.error('加载工作空间失败'));
  }, []);

  const openProject = (project: Project) => {
    setCurrentProjectId(project.id);
    navigate(`/workspace/project/${project.id}`);
  };

  const enterWork = async (path: string) => {
    const projectId = await resolveProjectId();
    if (!projectId) {
      setProjectOpen(true);
      message.warning('先选择或创建一个项目');
      return;
    }
    navigate(path);
  };

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <h1>工作空间</h1>
        <p>选择项目、查看当前状态，再进入项目理解、测试设计或测试执行。这里是开始工作的入口，不是测试产物目录。</p>
      </div>

      {currentProject && (
        <div className="product-summary">
          <div className="product-stat">
            <b>{currentProject.name}</b>
            <span>当前项目 · {currentProject.organization_name || '组织'}</span>
          </div>
          <div className="product-stat">
            <b>{STATUS_TEXT[currentProject.status || 'IDLE']?.text || '尚未测试'}</b>
            <span>当前测试状态</span>
          </div>
          <div className="product-stat">
            <b>{currentProject.success_rate != null ? `${currentProject.success_rate}%` : '-'}</b>
            <span>测试进度 / 成功率</span>
          </div>
          <div className="product-stat">
            <b>{currentProject.job_count ?? recentJobs.length}</b>
            <span>测试任务</span>
          </div>
        </div>
      )}

      <div className="product-card">
        <h2>工作入口</h2>
        <div className="product-modes">
          {WORKSPACE_LINKS.map((item) => (
            <button
              key={item.path}
              type="button"
              className="product-mode"
              onClick={() => void enterWork(item.path)}
            >
              <h3>{item.title}</h3>
              <p>{item.desc}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="product-card">
        <div className="product-card-head">
          <h2>我的空间</h2>
        </div>
        {personal.length === 0 ? <Empty description="还没有个人空间" /> : (
          <div className="product-grid">
            {personal.map((org) => <TeamTile key={org.id} org={org} />)}
          </div>
        )}
      </div>

      <div className="product-card">
        <div className="product-card-head">
          <h2>我的团队</h2>
          <Button type="primary" onClick={() => setTeamOpen(true)}>创建团队</Button>
        </div>
        {teams.length === 0 ? <Empty description="还没有团队，创建一个组织后邀请成员" /> : (
          <div className="product-grid">
            {teams.map((org) => <TeamTile key={org.id} org={org} />)}
          </div>
        )}
      </div>

      <div className="product-card">
        <div className="product-card-head">
          <h2>我的项目</h2>
          <Button onClick={() => setProjectOpen(true)}>创建项目</Button>
        </div>
        {projects.length === 0 ? <Empty description="还没有项目" /> : (
          <div className="product-grid">
            {projects.map((project) => {
              const status = STATUS_TEXT[project.status || 'IDLE'] || STATUS_TEXT.IDLE;
              return (
                <button key={project.id} type="button" className="product-tile" onClick={() => openProject(project)}>
                  <strong>{project.name}</strong>
                  <span>{project.organization_name || '组织'} · {project.member_count || 0} 名成员</span>
                  <em>
                    {project.success_rate != null ? `成功率 ${project.success_rate}%` : '还没有测试'}
                    {project.last_test_at ? ` · ${project.last_test_at}` : ''}
                  </em>
                  <em>进入项目</em>
                  <Tag color={status.color}>{status.text}</Tag>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="product-card">
        <h2>最近测试活动</h2>
        {recentActivity.length === 0 ? <Empty description="还没有测试活动记录" /> : recentActivity.map((item, index) => (
          <button key={`${item.project_id}-${index}`} type="button" className="product-result-item" onClick={() => {
            if (item.project_id) {
              setCurrentProjectId(item.project_id);
              navigate('/task');
            }
          }}>
            <span>{item.title}</span>
            <Tag>{item.status}</Tag>
          </button>
        ))}
        <p className="product-note">当前活动来自你有权限的测试任务，还没有独立的组织审计日志。</p>
      </div>

      <div className="product-two-col">
        <div className="product-card">
          <h2>最近测试</h2>
          {recentJobs.length === 0 ? <Empty description="还没有测试任务" /> : recentJobs.map((job) => (
            <button key={job.id} type="button" className="product-result-item" onClick={() => {
              setCurrentProjectId(job.project_id);
              navigate('/task');
            }}>
              <span>{job.name}</span>
              <Tag>{job.status}</Tag>
            </button>
          ))}
        </div>
        <div className="product-card">
          <h2>最近失败</h2>
          {recentFailures.length === 0 ? <Empty description="没有失败记录" /> : recentFailures.map((job) => (
            <button key={job.id} type="button" className="product-result-item" onClick={() => {
              setCurrentProjectId(job.project_id);
              navigate('/report');
            }}>
              <span>{job.name}</span>
              <Tag color="red">{job.result || 'FAILED'}</Tag>
            </button>
          ))}
        </div>
      </div>

      <Modal title="创建团队" open={teamOpen} onCancel={() => setTeamOpen(false)} onOk={() => teamForm.submit()} okText="创建">
        <Form form={teamForm} layout="vertical" onFinish={async (values) => {
          const created = await createOrganization(values.name, values.description, values.avatar);
          const orgId = created?.organization?.id;
          message.success('团队已创建');
          setTeamOpen(false);
          teamForm.resetFields();
          if (orgId) {
            navigate(`/workspace/org/${orgId}`);
          } else {
            load();
          }
        }}>
          <Form.Item name="name" label="团队名称" rules={[{ required: true, message: '请填写团队名称' }]}>
            <Input placeholder="例如：AI 测试团队" />
          </Form.Item>
          <Form.Item name="description" label="团队描述">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="avatar" label="团队头像">
            <Input placeholder="头像图片地址，可留空" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="创建项目" open={projectOpen} onCancel={() => setProjectOpen(false)} onOk={() => projectForm.submit()} okText="创建">
        <Form form={projectForm} layout="vertical" onFinish={async (values) => {
          const created = await createProject(Number(values.organization_id), values.name, values.description);
          message.success('项目已创建');
          setProjectOpen(false);
          projectForm.resetFields();
          if (created?.id) {
            setCurrentProjectId(created.id);
            navigate(`/workspace/project/${created.id}`);
          } else {
            load();
          }
        }}>
          <Form.Item name="organization_id" label="所属团队" rules={[{ required: true, message: '请选择团队' }]}>
            <select className="product-select">
              <option value="">请选择</option>
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>{org.name}</option>
              ))}
            </select>
          </Form.Item>
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请填写项目名称' }]}>
            <Input placeholder="例如：商城系统" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
