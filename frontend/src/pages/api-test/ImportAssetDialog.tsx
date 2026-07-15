/**
 * ImportAssetDialog - 从TestAsset导入用例到接口测试
 *
 * 支持：Draft / Published / Swagger / JSON
 * 数据源：TestAsset(API)
 * 禁止：AI生成（接口测试模块不生成，只从测试用例模块导入）
 */
import { useState, useEffect } from 'react';
import { Modal, Table, Tag, Button, Space, Select, message } from 'antd';
import { ImportOutlined, CheckCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

interface AssetItem {
  id: number;
  title: string;
  asset_type: string;
  status: string;
  source_type: string;
  executable: boolean;
  priority: string;
  tags?: string;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onImport: (assetIds: number[]) => void;
}

const statusConfig: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  reviewed: { color: 'purple', label: '已审查' },
  published: { color: 'success', label: '已发布' },
  executed: { color: 'green', label: '已执行' },
  failed: { color: 'error', label: '失败' },
};

export default function ImportAssetDialog({ visible, onClose, onImport }: Props) {
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('published');

  useEffect(() => {
    if (visible) {
      fetchAssets();
      setSelectedIds([]);
    }
  }, [visible, statusFilter]);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/assets/v2/list?asset_type=api&status=${statusFilter}&limit=100`, { credentials: 'include' });
      const data = await res.json();
      setAssets(data.items || []);
    } catch {
      message.error('获取用例列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleImport = () => {
    if (selectedIds.length === 0) {
      message.warning('请选择要导入的用例');
      return;
    }
    onImport(selectedIds);
    message.success(`已导入 ${selectedIds.length} 条用例`);
    onClose();
  };

  const columns: ColumnsType<AssetItem> = [
    { title: 'ID', dataIndex: 'id', width: 50 },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
    { title: '来源', dataIndex: 'source_type', width: 70, render: (v: string) => <Tag>{v}</Tag> },
    { title: '可执行', dataIndex: 'executable', width: 60, render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '是' : '否'}</Tag> },
  ];

  return (
    <Modal
      title={<Space><ImportOutlined /> 从测试用例导入</Space>}
      open={visible}
      onCancel={onClose}
      width={800}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleImport} disabled={selectedIds.length === 0}>
            导入 ({selectedIds.length})
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 12 }}>
        <span>筛选状态：</span>
        <Select value={statusFilter} onChange={setStatusFilter} style={{ width: 120 }} options={[
          { value: 'published', label: '已发布' },
          { value: 'draft', label: '草稿' },
          { value: 'reviewed', label: '已审查' },
        ]} />
      </Space>
      <Table
        dataSource={assets}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => setSelectedIds(keys as number[]),
        }}
        pagination={{ pageSize: 20 }}
        size="small"
      />
    </Modal>
  );
}
