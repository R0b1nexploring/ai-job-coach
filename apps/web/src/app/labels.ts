export const parseStatusLabels: Record<string, string> = {
  uploaded: '已上传',
  processing: '解析中',
  parsed: '已解析',
  needs_review: '需要核对',
  failed: '解析失败',
}

export const factStatusLabels: Record<string, string> = {
  extracted: '待确认',
  proposed: '用户补充，待确认',
  user_confirmed: '已确认',
  user_rejected: '已拒绝',
}

export const guardStatusLabels: Record<string, string> = {
  pending: '待检查',
  passed: '已通过',
  blocked: '已拦截',
}

export const reviewStatusLabels: Record<string, string> = {
  draft: '草稿',
  user_review: '待用户核对',
  advisor_review: '待顾问审核',
  approved: '已批准',
  rejected: '已退回',
}

export const dimensionLabels: Record<string, string> = {
  hard_requirements: '硬性条件',
  skills: '技能匹配',
  experience: '经历证据',
  keywords: '关键词覆盖',
  preferences: '求职偏好',
  freshness: '岗位时效',
}

export const quotaLabels: Record<string, string> = {
  match: '岗位匹配',
  resume: '定制简历',
  application: '辅助投递',
  interview: '模拟面试',
}
