// 简单 loading 旋转图标
interface LoadingProps {
  text?: string;
}

export default function Loading({ text = '加载中...' }: LoadingProps) {
  return (
    <div className="loading-wrap">
      <span className="loading" />
      <span>{text}</span>
    </div>
  );
}
