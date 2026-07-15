/**
 * Web - 页面管理
 *
 * 管理已抓取的页面和页面元素
 */
import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Space, Button, Input, message } from 'antd';
import { GlobalOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import request from '../../services/request';
import { PageHeader } from '../../components/UI';

interface PageItem {
  id: number;
  task_name: string;
  page_url: string;
  status: string;
  task_type: string;
  created_at: string;
}

export default function WebPages() {
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState('');

  const fetchPages = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/tasks', {
        params: { skip: (page - 1) * 20, limit: 20, task_type: 'web', keyword: keyword.trim() || undefined },
      });
      const data = res?.data || res;
      setPages(data?.items || []);
      setTotal(data?.total || 0);
    } catch (e) {
      console.error('[WebPages] fetchPages failed:', e);
      message.error('加载页面列表失败');
      setPages([]);
    } finally {
      setLoading(false);
    }
  }, [page, keyword]);

  useEffect(() => { fetchPages(); }, [fetchPages]);

  return (
    <div>
      <PageHeader title="页面管理" subtitle="管理已抓取的页面和页面元素" icon={<GlobalOutlined />} />
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索页面"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={fetchPages}
            style={{ width: 250 }}
            prefix={<SearchOutlined />}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchPages}>刷新</Button>
        </Space>
        <Table
          dataSource={pages}
          rowKey="id"
          loading={loading}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            { title: '页面名称', dataIndex: 'task_name', ellipsis: true },
            { title: 'URL', dataIndex: 'page_url', ellipsis: true, render: (url: string) => url ? <a href={url} target="_blank" rel="noreferrer">{url}</a> : '-' },
            { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'success' ? 'green' : s === 'failed' ? 'red' : 'blue'}>{s}</Tag> },
            { title: '创建时间', dataIndex: 'created_at', width: 160 },
          ]}
        />
      </Card>
    </div>
  );
}
