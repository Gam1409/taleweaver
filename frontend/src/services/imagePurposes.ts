export const imagePurposes = [
  {
    id: 'npc',
    label: 'NPC portraits',
    hint: 'Character cards and updated portraits in a session.',
    quality: 'profile_model_quality',
    fallback: 'advanced'
  },
  {
    id: 'protagonist',
    label: 'Hero portraits',
    hint: 'The adventure protagonist.',
    quality: 'protagonist_model_quality',
    fallback: 'advanced'
  },
  {
    id: 'object',
    label: 'Items',
    hint: 'Readable, isolated inventory objects.',
    quality: 'asset_model_quality',
    fallback: 'simple'
  },
  {
    id: 'background',
    label: 'Location backgrounds',
    hint: 'Places, including locations created during play.',
    quality: 'scene_model_quality',
    fallback: 'advanced'
  },
  {
    id: 'illustration',
    label: 'Story illustrations',
    hint: 'Characters and actions at a specific story moment.',
    quality: 'scene_model_quality',
    fallback: 'advanced'
  },
  {
    id: 'cover',
    label: 'Adventure covers',
    hint: 'The adventure cover composition.',
    quality: 'cover_model_quality',
    fallback: 'advanced'
  },
  {
    id: 'avatar',
    label: 'Account avatars',
    hint: 'Player profile pictures.',
    quality: '',
    fallback: 'simple'
  },
  {
    id: 'catalog',
    label: 'Style previews',
    hint: 'Preview tiles for styles and tones.',
    quality: '',
    fallback: 'simple'
  }
] as const
export type ImagePurpose = (typeof imagePurposes)[number]['id']
export type PresetAssignment = ImagePurpose | 'simple' | 'advanced'
