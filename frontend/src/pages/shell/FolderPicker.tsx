import { useRef } from 'react';
import { Button, message } from 'antd';

export default function FolderPicker({
  label,
  disabled,
  onPick,
}: {
  label: string;
  disabled?: boolean;
  onPick: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const bind = (el: HTMLInputElement | null) => {
    inputRef.current = el;
    if (!el) return;
    el.setAttribute('webkitdirectory', 'true');
    el.setAttribute('directory', 'true');
    (el as HTMLInputElement & { webkitdirectory?: boolean }).webkitdirectory = true;
  };

  return (
    <>
      <Button disabled={disabled} onClick={() => inputRef.current?.click()}>{label}</Button>
      <input
        ref={bind}
        type="file"
        multiple
        className="pw-folder-input"
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = '';
          if (!files.length) {
            message.error('没有读到文件夹里的文件，请再选一次');
            return;
          }
          onPick(files);
        }}
      />
    </>
  );
}
