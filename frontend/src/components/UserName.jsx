import './UserName.css'

export default function UserName({ user, className = '' }) {
  const handle = user?.username || user?.display_name
  const tooltip = user?.full_name && user.full_name !== handle ? user.full_name : null

  if (!tooltip) {
    return <span className={className}>{handle}</span>
  }
  return (
    <span className={`username-hover ${className}`} data-tooltip={tooltip}>
      {handle}
    </span>
  )
}
