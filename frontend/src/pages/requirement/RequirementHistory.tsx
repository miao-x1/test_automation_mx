/**
 * 需求历史页
 *
 * 展示所有需求处理历史，支持筛选/搜索
 */
import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Space, Input, Popconfirm, message } from 'antd';
import { HistoryOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import { getRequirementTasks, RequirementTask } from '../../services/requirement';
import request from '../../services/request';
import { StatusTag, PageHeader, EmptyGuide } from '../../components/UI';

export default function RequirementHistory() {
  const navigate = useNavigate();
  const [history, setHistory] = useState<RequirementTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getRequirementTasks() as any;
      setHistory(Array.isArray(res?.data || res) ? (res?.data || res) : []);
    } catch {
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
      <PageHeader title="需求历史" subtitle="所有需求处理记录" icon={<HistoryOutlined />} />
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Input.Search placeholder="搜索需求" value={keyword} onChange={e => setKeyword(e.target.value)} style={{ width: 250 }} prefix={<SearchOutlined />} />
          <Button icon={<ReloadOutlined />} onClick={fetchHistory} loading={loading}>刷新</Button>
        </Space>
        {filteredHistory.length === 0 && !loading ? (
          <EmptyGuide title="暂无历史记录" description="创建第一个测试需求开始" actionLabel="新建需求" actionTo="/requirement/create" />
        ) : (
          <Table
            columns={[
              { title: 'ID', dataIndex: 'id', width: 50 },
              { title: '需求', dataIndex: 'requirement', ellipsis: true },
              { title: '状态', dataIndex: 'status', width: 90, render: (s: string) => <StatusTag status={s} size="small" /> },
              { title: '时间', dataIndex: 'created_at', width: 150 },
              {
                title: '操作', width: 150,
                render: (_: unknown, r: RequirementTask) => (
                  <Space size="small">
                    <Button size="small" onClick={() => navigate(`/requirement/detail/${r.id}`)}>详情</Button>
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
