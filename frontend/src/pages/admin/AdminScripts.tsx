import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Input, Button, Space, Tag, message } from 'antd';
import { CodeOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface ScriptItem {
  id: number;
  name: string;
  language: string;
  framework: string;
  task_id: number;
  description: string;
  created_at: string;
}

export default function AdminScripts() {
  const [list, setList] = useState<ScriptItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [keyword, setKeyword] = useState('');

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/scripts', {
        params: { page, page_size: pageSize, keyword },
      });
      const data = res?.data || {};
      setList(data.items || []);
      setTotal(data.total || 0);
    } catch {
      message.error('获取脚本列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleSearch = (value: string) => {
    setKeyword(value);
    setPage(1);
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: '脚本名', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '语言',
      dataIndex: 'language',
      key: 'language',
      render: (t: string) => <Tag color="blue">{t || '-'}</Tag>,
    },
    {
      title: '框架',
      dataIndex: 'framework',
      key: 'framework',
      render: (t: string) => t || '-',
    },
    {
      title: '任务ID',
      dataIndex: 'task_id',
      key: 'task_id',
      width: 90,
      render: (t: number) => t ?? '-',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (t: string) => t || '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  ];

  return (
    <div>
      <PageHeader title="脚本仓库" subtitle="管理脚本模板和公共脚本库" icon={<CodeOutlined />} />
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索脚本名"
            allowClear
            onSearch={handleSearch}
            style={{ width: 260 }}
            prefix={<SearchOutlined />}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchList}>
            刷新
          </Button>
        </Space>
        <Table
          columns={columns}
          dataSource={list}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => setPage(p),
          }}
        />
      </Card>
    </div>
  );
}
