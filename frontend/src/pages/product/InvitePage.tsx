import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, message } from 'antd';
import { acceptInvite, declineInvite, getInvite } from '@/services/workspace';
import { setCurrentProjectId } from './projectStore';
import './product.css';

const STATUS_TEXT: Record<string, string> = {
  pending: '待接受',
  accepted: '邀请已被接受',
  cancelled: '邀请已取消',
  declined: '邀请已拒绝',
  expired: '邀请已过期',
};

export default function InvitePage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<any>(null);

  useEffect(() => {
    if (!token) return;
    getInvite(token).then(setInfo).catch(() => setInfo({ status: 'missing' }));
  }, [token]);

  const accept = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const data = await acceptInvite(token);
      if (data?.project_id) setCurrentProjectId(data.project_id);
      message.success('已加入团队');
      navigate(data?.organization_id ? `/workspace/org/${data.organization_id}` : '/workspace');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || '邀请无效');
    } finally {
      setBusy(false);
    }
  };

  const decline = async () => {
    if (!token) return;
    setBusy(true);
    try {
      await declineInvite(token);
      message.success('已拒绝邀请');
      navigate('/workspace');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || '无法拒绝该邀请');
    } finally {
      setBusy(false);
    }
  };

  const pending = info?.status === 'pending' && !info?.email_mismatch;

  return (
    <div className="product-shell">
      <div className="product-card" style={{ textAlign: 'center', padding: 48 }}>
        <h1>加入团队</h1>
        <p>{info?.organization_name ? `邀请你加入「${info.organization_name}」` : '接受邀请后，你可以进入对应项目并按分配的角色协作测试。'}</p>
        <p className="product-note">{STATUS_TEXT[info?.status] || (info?.status === 'missing' ? '邀请不存在' : '正在核对邀请')}</p>
        {info?.email_mismatch && <p className="product-note">当前登录邮箱与邀请邮箱不一致，请切换账号后再接受。</p>}
        <Button type="primary" loading={busy} disabled={!pending} onClick={accept}>接受邀请</Button>
        <Button style={{ marginLeft: 12 }} loading={busy} disabled={!pending} onClick={decline}>拒绝邀请</Button>
      </div>
    </div>
  );
}
