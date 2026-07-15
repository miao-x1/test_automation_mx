/**
 * 需求模块 - 需求列表
 *
 * 展示所有需求记录，支持筛选/搜索/分页
 * 输入层：不参与执行
 */
import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Space, Input, Popconfirm, message } from 'antd';
import { HistoryOutlined, SearchOutlined, ReloadOutlined, PlusOutlined } from '@ant-design/icons';
import { getRequirementTasks, RequirementTask } from '../../services/requirement';
import request from '../../services/request';
import { StatusTag, PageHeader, EmptyGuide } from '../../components/UI';

export default function RequirementList() {
  const navigate = useNavigate();
  const [history, setHistory] = useState<RequirementTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getRequirementTasks() as any;
      setHistory(Array.isArray(res?.data || res) ? (res?.data || res) : []);
    } catch (e) {
      console.error('[RequirementList] fetch failed:', e);
      setHistory([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const handleDelete = async (id: number) => {
    try {
      await request.delete(`/requirement/${id}`);
      message.success('删除成功');
      fetchHistory();
    } catch {
      message.error('删除失败');
    }
  };

  const filteredHistory = keyword
    ? history.filter((r: RequirementTask) => r.requirement?.includes(keyword))
    : history;

  return (
    <div>
      <PageHeader title="需求列表" subtitle="查看所有需求记录" icon={<HistoryOutlined />} />
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索需求内容"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            style={{ width: 250 }}
            prefix={<SearchOutlined />}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchHistory} loading={loading}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/requirement/create')}>创建需求</Button>
        </Space>
        {filteredHistory.length === 0 && !loading ? (
          <EmptyGuide title="暂无需求记录" description="创建第一个测试需求开始" actionLabel="创建需求" actionTo="/requirement/create" />
        ) : (
          <Table
            columns={[
              { title: 'ID', dataIndex: 'id', width: 50 },
              { title: '需求', dataIndex: 'requirement', ellipsis: true },
              { title: '状态', dataIndex: 'status', width: 90, render: (s: string) => <StatusTag status={s} size="small" /> },
              { title: '关联任务', dataIndex: 'task_id', width: 80, render: (tid: number | null) => tid ? <Button type="link" size="small" onClick={() => navigate(`/web/task/${tid}`)}>#{tid}</Button> : '-' },
              { title: '时间', dataIndex: 'created_at', width: 150 },
              {
                title: '操作', width: 200,
                render: (_: unknown, r: RequirementTask) => (
                  <Space size="small">
                    <Button size="small" onClick={() => navigate(`/requirement/detail/${r.id}`)}>详情</Button>
                    {r.task_id && <Button type="link" size="small" onClick={() => navigate(`/web/task/${r.task_id}`)}>查看任务</Button>}
                    <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)} okText="确定" cancelText="取消">
                      <Button size="small" danger>删除</Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
            dataSource={filteredHistory}
            rowKey="id"
            loading={loading}
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>
    </div>
  );
}
