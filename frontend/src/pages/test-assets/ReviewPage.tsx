import { useState, useEffect, useCallback } from 'react';
import { Table, Tag, Button, Space, Input, Select, message } from 'antd';
import { EyeOutlined, PlayCircleOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { assetTypeConfig, sourceConfig, type AssetItem, runCase } from './constants';

interface Props {
  onDetail: (id: number) => void;
}

export default function ReviewPage({ onDetail }: Props) {
  const [items, setItems] = useState<AssetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [filterType, setFilterType] = useState<string | undefined>();
  const [filterKeyword, setFilterKeyword] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        skip: String((page - 1) * pageSize),
        limit: String(pageSize),
        status: 'reviewed',
      });
      if (filterType) params.set('asset_type', filterType);
      if (filterKeyword) params.set('keyword', filterKeyword);

      const res = await fetch(`/api/assets/v2/list?${params}`, { credentials: 'include' });
      const data = await res.json();
      if (data.items) { setItems(data.items); setTotal(data.total); }
    } catch { message.error('加载失败'); }
    finally { setLoading(false); }
  }, [page, pageSize, filterType, filterKeyword]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handlePublish = async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const res = await fetch('/workflow/publish', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ asset_ids: selectedRowKeys.map(Number) }),
      });
      const data = await res.json();
      if (data.published) {
        message.success(`发布 ${data.published} 条`);
        setSelectedRowKeys([]);
        fetchData();
      }
    } catch { message.error('发布失败'); }
  };

  const columns: ColumnsType<AssetItem> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '类型', dataIndex: 'asset_type', width: 100, render: (v: string) => <Tag color={assetTypeConfig[v]?.color || 'blue'}>{assetTypeConfig[v]?.label || v}</Tag> },
    { title: '来源', dataIndex: 'source_type', width: 80, render: (v: string) => <Tag color={sourceConfig[v]?.color || 'default'}>{sourceConfig[v]?.label || v}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 70, render: (v: string) => <Tag color={v === 'P0' ? 'red' : v === 'P1' ? 'orange' : 'blue'}>{v}</Tag> },
    { title: '操作', width: 140, render: (_: any, r: AssetItem) => (
      <Space size="small">
        <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => onDetail(r.id)}>详情</Button>
        {r.executable && (
          <Button size="small" type="link" icon={<PlayCircleOutlined />} onClick={async () => {
            try { const res = await runCase(r.id); message.success(`执行已提交 (ID: ${res.execution_id})`); fetchData(); }
            catch (e: any) { message.error(e?.message || '执行失败'); }
          }}>执行</Button>
        )}
      </Space>
    )},
  ];

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input placeholder="关键词" prefix={<SearchOutlined />} value={filterKeyword} onChange={e => setFilterKeyword(e.target.value)} style={{ width: 180 }} allowClear />
        <Select placeholder="类型" value={filterType} onChange={setFilterType} allowClear style={{ width: 110 }}
          options={Object.entries(assetTypeConfig).map(([k, v]) => ({ value: k, label: v.label }))} />
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
        {selectedRowKeys.length > 0 && (
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={handlePublish}>
            批量发布 ({selectedRowKeys.length})
          </Button>
        )}
      </Space>
      <Table
        dataSource={items} columns={columns} rowKey="id" loading={loading}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        pagination={{ current: page, pageSize, total, onChange: (p, ps) => { setPage(p); setPageSize(ps); }, showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
        size="small"
      />
    </div>
  );
}
