import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Form, Input, Modal, Popconfirm, Select, Table, Tag, message } from 'antd';
import {
  addProjectMember,
  deleteProject,
  getProject,
  removeProjectMember,
  updateProject,
  updateProjectMember,
  type Member,
  type Project,
  type ProjectRole,
} from '@/services/workspace';
import { setCurrentProjectId } from './projectStore';
import './product.css';

const ROLE_TEXT: Record<string, string> = {
  PROJECT_ADMIN: 'Maintainer',
  TESTER: 'Developer',
  REPORTER: 'Reporter',
  VIEWER: 'Viewer',
  GUEST: 'Viewer',
};

const ROLE_OPTIONS = [
  { value: 'PROJECT_ADMIN', label: 'Maintainer · 管理项目' },
  { value: 'TESTER', label: 'Developer · 执行测试' },
  { value: 'REPORTER', label: 'Reporter · 查看报告' },
  { value: 'VIEWER', label: 'Viewer · 仅看项目信息' },
];

export default function ProjectPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [canAdmin, setCanAdmin] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [form] = Form.useForm();
  const [settingsForm] = Form.useForm();

  const load = async () => {
    const data = await getProject(projectId);
    setProject(data.project);
    setMembers(data.members || []);
    setCanAdmin(!!data.can_admin);
    setCurrentProjectId(projectId);
    settingsForm.setFieldsValue({
      name: data.project?.name,
      description: data.project?.description,
    });
  };

  useEffect(() => {
    if (!projectId) return;
    load().catch(() => {
      message.error('没有该项目的权限');
      navigate('/workspace');
    });
  }, [projectId]);

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <p><Link to="/workspace">工作空间</Link> / {project?.organization_name}</p>
        <h1>{project?.name || '项目'}</h1>
        <p>{project?.description || '进入后使用原来的测试平台。'}</p>
        <div className="product-cta">
          <Button type="primary" onClick={() => {
            setCurrentProjectId(projectId);
            navigate('/task/create');
          }}>进入测试平台</Button>
        </div>
      </div>

      <div className="product-card">
        <div className="product-card-head">
          <h2>项目成员</h2>
          {canAdmin && <Button type="primary" onClick={() => setMemberOpen(true)}>添加成员</Button>}
        </div>
        <Table
          rowKey="id"
          dataSource={members}
          pagination={false}
          columns={[
            { title: '成员', render: (_: unknown, r: Member) => r.display_name || r.username },
            {
              title: '权限',
              dataIndex: 'role',
              render: (role: string, r: Member) => canAdmin ? (
                <Select
                  value={(role === 'GUEST' ? 'VIEWER' : role) as ProjectRole}
                  style={{ width: 220 }}
                  options={ROLE_OPTIONS}
                  onChange={async (next: ProjectRole) => {
                    await updateProjectMember(projectId, r.id, next);
                    message.success('权限已更新');
                    load();
                  }}
                />
              ) : <Tag>{ROLE_TEXT[role] || role}</Tag>,
            },
            {
              title: '操作',
              render: (_: unknown, r: Member) => canAdmin ? (
                <Button danger type="link" onClick={async () => {
                  await removeProjectMember(projectId, r.id);
                  message.success('已移除');
                  load();
                }}>移除</Button>
              ) : null,
            },
          ]}
        />
      </div>

      <div className="product-card">
        <h2>项目设置</h2>
        <Form form={settingsForm} layout="vertical" onFinish={async (values) => {
          await updateProject(projectId, values.name, values.description);
          message.success('已更新');
          load();
        }}>
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input disabled={!canAdmin} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} disabled={!canAdmin} />
          </Form.Item>
          {canAdmin && <Button type="primary" htmlType="submit">保存</Button>}
        </Form>
        {canAdmin && !project?.is_default && (
          <Popconfirm title="删除后成员将无法再进入" onConfirm={async () => {
            await deleteProject(projectId);
            message.success('项目已删除');
            navigate('/workspace');
          }}>
            <Button danger style={{ marginTop: 24 }}>删除项目</Button>
          </Popconfirm>
        )}
      </div>

      <Modal title="添加项目成员" open={memberOpen} onCancel={() => setMemberOpen(false)} onOk={() => form.submit()} okText="添加">
        <Form form={form} layout="vertical" onFinish={async (values) => {
          await addProjectMember(projectId, values);
          message.success('已加入项目');
          setMemberOpen(false);
          form.resetFields();
          load();
        }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input placeholder="已注册用户的用户名" />
          </Form.Item>
          <Form.Item name="role" label="权限" initialValue="TESTER">
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
