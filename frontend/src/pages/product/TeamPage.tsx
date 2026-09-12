import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Form, Input, Modal, Select, Table, Tag, message } from 'antd';
import {
  cancelInvite,
  createProject,
  getOrganization,
  inviteMember,
  listOrgInvites,
  removeOrgMember,
  updateOrganization,
  updateOrgMember,
  type Member,
  type Organization,
  type OrgInvite,
  type OrgRole,
  type Project,
} from '@/services/workspace';
import { setCurrentProjectId } from './projectStore';
import './product.css';

const ROLE_TEXT: Record<string, string> = {
  OWNER: 'Owner',
  ADMIN: 'Admin',
  MEMBER: 'Member',
};

const INVITE_TEXT: Record<string, string> = {
  pending: '待接受',
  accepted: '已接受',
  cancelled: '已取消',
  declined: '已拒绝',
  expired: '已过期',
};

export default function TeamPage() {
  const { id } = useParams();
  const orgId = Number(id);
  const navigate = useNavigate();
  const [org, setOrg] = useState<Organization | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [invites, setInvites] = useState<OrgInvite[]>([]);
  const [myRole, setMyRole] = useState<string>('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [inviteLink, setInviteLink] = useState('');
  const [form] = Form.useForm();
  const [orgForm] = Form.useForm();
  const [projectForm] = Form.useForm();
  const canAdmin = myRole === 'OWNER' || myRole === 'ADMIN';

  const load = async () => {
    const data = await getOrganization(orgId);
    setOrg(data.organization);
    setMembers(data.members || []);
    setProjects(data.projects || []);
    setMyRole(data.my_role || '');
    orgForm.setFieldsValue({
      name: data.organization?.name,
      description: data.organization?.description,
      avatar: data.organization?.avatar,
    });
    if ((data.my_role === 'OWNER' || data.my_role === 'ADMIN')) {
      const inviteRes = await listOrgInvites(orgId);
      setInvites(inviteRes?.items || []);
    } else {
      setInvites([]);
    }
  };

  useEffect(() => {
    if (!orgId) return;
    load().catch(() => message.error('无法打开团队'));
  }, [orgId]);

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <p><Link to="/workspace">工作空间</Link></p>
        <div className="product-tile-head">
          {org?.avatar ? <img className="product-avatar" src={org.avatar} alt="" /> : <span className="product-avatar product-avatar-fallback">{(org?.name || '团').slice(0, 1)}</span>}
          <h1>{org?.name || '团队'}</h1>
        </div>
        <p>{org?.description || '管理团队成员、邀请和项目。'}</p>
        <p className="product-note">{org?.member_count ?? members.length} 名成员 · {org?.project_count ?? projects.length} 个项目 · 我的角色：{ROLE_TEXT[myRole] || myRole || '-'}</p>
      </div>

      {canAdmin && (
        <div className="product-card">
          <h2>团队信息</h2>
          <Form form={orgForm} layout="vertical" onFinish={async (values) => {
            await updateOrganization(orgId, values.name, values.description, values.avatar);
            message.success('团队已更新');
            load();
          }}>
            <Form.Item name="name" label="团队名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="description" label="团队简介">
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item name="avatar" label="团队头像">
              <Input placeholder="头像图片地址" />
            </Form.Item>
            <Button type="primary" htmlType="submit">保存</Button>
          </Form>
        </div>
      )}

      <div className="product-card">
        <div className="product-card-head">
          <h2>项目</h2>
          {canAdmin && <Button type="primary" onClick={() => setProjectOpen(true)}>创建项目</Button>}
        </div>
        <div className="product-grid">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className="product-tile"
              onClick={() => {
                setCurrentProjectId(project.id, project.name);
                navigate('/workbench');
              }}
            >
              <strong>{project.name}</strong>
              <span>{project.member_count || 0} 名成员</span>
              <em>{project.status || 'IDLE'}</em>
            </button>
          ))}
        </div>
      </div>

      <div className="product-card">
        <div className="product-card-head">
          <h2>成员</h2>
          {canAdmin && <Button type="primary" onClick={() => setInviteOpen(true)}>邀请成员</Button>}
        </div>
        <Table
          rowKey="id"
          dataSource={members}
          pagination={false}
          columns={[
            {
              title: '成员',
              render: (_: unknown, r: Member) => (
                <span className="product-tile-head">
                  {r.avatar ? <img className="product-avatar sm" src={r.avatar} alt="" /> : <span className="product-avatar product-avatar-fallback sm">{(r.display_name || r.username || '?').slice(0, 1)}</span>}
                  {r.display_name || r.username}
                </span>
              ),
            },
            { title: '用户名', dataIndex: 'username' },
            {
              title: '角色',
              dataIndex: 'role',
              render: (role: string, r: Member) => canAdmin && role !== 'OWNER' ? (
                <Select
                  value={role as OrgRole}
                  style={{ width: 140 }}
                  options={[
                    { value: 'ADMIN', label: 'Admin' },
                    { value: 'MEMBER', label: 'Member' },
                  ]}
                  onChange={async (next: OrgRole) => {
                    await updateOrgMember(orgId, r.id, next);
                    message.success('角色已更新');
                    load();
                  }}
                />
              ) : <Tag>{ROLE_TEXT[role] || role}</Tag>,
            },
            { title: '加入时间', dataIndex: 'joined_at', render: (v: string) => v || '-' },
            { title: '最近活动', render: () => '暂无成员活动记录' },
            {
              title: '操作',
              render: (_: unknown, r: Member) => canAdmin && r.role !== 'OWNER' ? (
                <Button danger type="link" onClick={async () => {
                  await removeOrgMember(orgId, r.id);
                  message.success('已移除');
                  load();
                }}>移除</Button>
              ) : null,
            },
          ]}
        />
      </div>

      {canAdmin && (
        <div className="product-card">
          <h2>邀请</h2>
          <Table
            rowKey="id"
            dataSource={invites}
            pagination={false}
            columns={[
              { title: '邮箱', dataIndex: 'email', render: (v: string) => v || '邀请链接' },
              { title: '角色', dataIndex: 'role' },
              { title: '状态', dataIndex: 'status', render: (v: string) => INVITE_TEXT[v] || v },
              { title: '过期时间', dataIndex: 'expires_at', render: (v: string) => v || '-' },
              {
                title: '操作',
                render: (_: unknown, row: OrgInvite) => row.status === 'pending' ? (
                  <Button danger type="link" onClick={async () => {
                    await cancelInvite(orgId, row.id);
                    message.success('邀请已取消');
                    load();
                  }}>取消邀请</Button>
                ) : null,
              },
            ]}
          />
        </div>
      )}

      <Modal
        title="邀请成员"
        open={inviteOpen}
        onCancel={() => { setInviteOpen(false); setInviteLink(''); }}
        onOk={() => form.submit()}
        okText="生成邀请"
      >
        <Form form={form} layout="vertical" onFinish={async (values) => {
          const data = await inviteMember(orgId, {
            email: values.email,
            role: values.role,
            project_id: values.project_id,
            project_role: values.project_role,
          });
          const path = data?.invite_path || `/workspace/invite/${data?.token}`;
          const link = `${window.location.origin}${path}`;
          setInviteLink(link);
          message.success('邀请已生成，请把链接发给对方');
          load();
        }}>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="对方注册邮箱；留空则只生成邀请链接" />
          </Form.Item>
          <Form.Item name="role" label="团队角色" initialValue="MEMBER">
            <Select options={[{ value: 'MEMBER', label: 'Member' }, { value: 'ADMIN', label: 'Admin' }]} />
          </Form.Item>
          <Form.Item name="project_id" label="同时加入项目">
            <Select
              allowClear
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="project_role" label="项目角色" initialValue="TESTER">
            <Select options={[
              { value: 'PROJECT_ADMIN', label: 'Maintainer' },
              { value: 'TESTER', label: 'Developer' },
              { value: 'REPORTER', label: 'Reporter' },
              { value: 'VIEWER', label: 'Viewer' },
            ]} />
          </Form.Item>
        </Form>
        {inviteLink && (
          <p className="product-note">邀请链接：<a href={inviteLink}>{inviteLink}</a></p>
        )}
      </Modal>

      <Modal title="创建项目" open={projectOpen} onCancel={() => setProjectOpen(false)} onOk={() => projectForm.submit()} okText="创建">
        <Form form={projectForm} layout="vertical" onFinish={async (values) => {
          const created = await createProject(orgId, values.name, values.description);
          message.success('项目已创建');
          setProjectOpen(false);
          projectForm.resetFields();
          if (created?.id) {
            setCurrentProjectId(created.id, created.name);
            navigate('/workbench');
          } else {
            load();
          }
        }}>
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input placeholder="例如：商城系统" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
