"use client";

import { useState } from "react";

interface PlayerAvatarProps {
  headshotUrl: string | null;
  teamColor: string | null;
  size?: "sm" | "xl";
}

const SIZE_CLASSES = {
  sm: "h-9 w-9",
  xl: "h-[92px] w-[92px] border-4 border-surface",
};

/** A player's photo on a team-colored disc; a silhouette stands in when there is none. */
export default function PlayerAvatar({
  headshotUrl,
  teamColor,
  size = "sm",
}: PlayerAvatarProps) {
  const [failed, setFailed] = useState(false);
  const showPhoto = headshotUrl !== null && !failed;

  return (
    <span
      className={`relative inline-block flex-none rounded-full ${SIZE_CLASSES[size]}`}
      style={{ background: teamColor ?? "var(--ink-3)" }}
    >
      <span className="block h-full w-full overflow-hidden rounded-full">
        {showPhoto ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={headshotUrl}
            alt=""
            onError={() => setFailed(true)}
            className="h-full w-full object-cover object-top"
          />
        ) : (
          <svg viewBox="0 0 40 40" aria-hidden="true" className="block h-full w-full">
            <circle cx="20" cy="15" r="7.5" fill="rgba(255,255,255,.88)" />
            <path
              d="M4 40c1.2-9.5 7.5-14.5 16-14.5S34.8 30.5 36 40z"
              fill="rgba(255,255,255,.88)"
            />
          </svg>
        )}
      </span>
    </span>
  );
}
