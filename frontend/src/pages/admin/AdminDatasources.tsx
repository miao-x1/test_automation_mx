import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Modal, Form, Input, Select, Space, Tag, message } from 'antd';
import { DatabaseOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface DsItem {
  id: number;
  name: string;
  type: string;
  host: string;
  port: number;
  status: string;
}

export default function AdminDatasources() {
  const [list, setList] = useState<DsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/datasources');
      const data = res?.data;
      setList(Array.isArray(data) ? data : data?.items || []);
    } catch {
      message.error('获取数据源列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const res: any = await request.post('/admin/datasources', values);
      if (res?.code === 200) {
        message.success('创建成功');
        setModalOpen(false);
        form.resetFields();
        fetchList();
      } else {
        message.error(res?.message || '创建失败');
      }
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验未通过
      message.error('创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (t: string) => <Tag color="purple">{t || '-'}</Tag>,
    },
    { title: 'Host', dataIndex: 'host', key: 'host' },
    { title: 'Port', dataIndex: 'port', key: 'port', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={s === 'active' || s === 'online' ? 'success' : 'default'}>{s || '-'}</Tag>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="数据源管理" subtitle="管理数据库连接和API端点" icon={<DatabaseOutlined />} />
      <Card
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchList}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              创建数据源
            </Button>
          </Space>
        }
      >
        <Table columns={columns} dataSource={list} rowKey="id" loading={loading} pagination={false} />
      </Card>
      <Modal
        title="创建数据源"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="数据源名称" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select
              placeholder="选择数据源类型"
              options={[
                { value: 'mysql', label: 'MySQL' },
                { value: 'postgresql', label: 'PostgreSQL' },
                { value: 'mongodb', label: 'MongoDB' },
                { value: 'redis', label: 'Redis' },
                { value: 'api', label: 'API' },
              ]}
            />
          </Form.Item>
          <Form.Item name="host" label="Host" rules={[{ required: true, message: '请输入 Host' }]}>
            <Input placeholder="127.0.0.1" />
          </Form.Item>
          <Form.Item name="port" label="Port" rules={[{ required: true, message: '请输入 Port' }]}>
            <Input type="number" placeholder="3306" />
          </Form.Item>
          <Form.Item name="database" label="数据库">
            <Input placeholder="数据库名（可选）" />
          </Form.Item>
          <Form.Item name="username" label="用户名">
            <Input placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" label="密码">
            <Input.Password placeholder="密码" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
