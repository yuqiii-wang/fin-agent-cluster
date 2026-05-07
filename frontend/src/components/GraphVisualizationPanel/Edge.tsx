export interface EdgeProps {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  color: string;
}

export function Edge({ fromX, fromY, toX, toY, color }: EdgeProps) {
  const d = `M ${fromX} ${fromY} L ${toX} ${toY}`;
  return (
    <path
      d={d}
      stroke={color}
      strokeWidth={1.5}
      fill="none"
      markerEnd="url(#graph-arrow)"
      opacity={0.55}
    />
  );
}
