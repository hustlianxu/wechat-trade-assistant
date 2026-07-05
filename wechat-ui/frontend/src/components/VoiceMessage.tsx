import { useState } from 'react'
import { api } from '../api/client'
import type { TranscribeResult } from '../types'

interface Props {
  username: string
  localId: number
  /** 语音时长（毫秒，来自 parsed.length）。 */
  lengthMs?: number
  /** 后端预填的转录文本（如有）。 */
  initialTranscription?: string
}

/**
 * 语音消息组件
 * - 播放按钮：点击加载 /api/voice/{username}/{local_id} 的 WAV 并播放
 * - 时长显示
 * - 转录按钮：点击调用 POST /api/transcribe，显示转录文本
 */
export default function VoiceMessage({
  username,
  localId,
  lengthMs = 0,
  initialTranscription = '',
}: Props) {
  const [audio, setAudio] = useState<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState<boolean>(false)

  const [transcription, setTranscription] = useState<string>(initialTranscription)
  const [transcribing, setTranscribing] = useState<boolean>(false)
  const [transcribeSource, setTranscribeSource] = useState<string>('')
  const [transcribeError, setTranscribeError] = useState<string>('')

  /** 时长秒数（向上取整）。 */
  const durationSec = Math.max(1, Math.ceil((lengthMs || 0) / 1000))

  /** 播放 / 暂停切换。 */
  const handleTogglePlay = () => {
    if (playing && audio) {
      audio.pause()
      setPlaying(false)
      return
    }
    // 复用已加载的 audio
    if (audio) {
      audio.currentTime = 0
      void audio.play()
      setPlaying(true)
      return
    }
    const url = api.voiceUrl(username, localId)
    const a = new Audio(url)
    a.addEventListener('ended', () => setPlaying(false))
    a.addEventListener('error', () => {
      setPlaying(false)
      setTranscribeError('语音加载失败')
    })
    setAudio(a)
    void a.play().then(() => setPlaying(true)).catch(() => {
      setPlaying(false)
      setTranscribeError('语音播放失败，可能缺少 SILK 解码依赖')
    })
  }

  /** 调用转录 API。 */
  const handleTranscribe = async () => {
    setTranscribing(true)
    setTranscribeError('')
    try {
      const result: TranscribeResult = await api.transcribe(username, localId)
      setTranscription(result.text)
      setTranscribeSource(result.source)
    } catch (e) {
      setTranscribeError(e instanceof Error ? e.message : '转录失败')
    } finally {
      setTranscribing(false)
    }
  }

  const sourceLabel = transcribeSource === 'whisper_cpp'
    ? '本地 whisper.cpp'
    : transcribeSource === 'llm'
      ? 'LLM API'
      : transcribeSource === 'error'
        ? '失败'
        : ''

  return (
    <div className="voice-msg">
      <div className="voice-msg__main">
        <button
          className={`voice-msg__play ${playing ? 'voice-msg__play--playing' : ''}`}
          onClick={handleTogglePlay}
          title={playing ? '暂停' : '播放'}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="voice-msg__duration">{durationSec}"</span>
        <button
          className="voice-msg__transcribe-btn"
          onClick={handleTranscribe}
          disabled={transcribing}
        >
          {transcribing ? '转录中…' : '转录'}
        </button>
      </div>

      {transcribeError && <div className="voice-msg__error">{transcribeError}</div>}

      {transcription && (
        <div className="voice-msg__transcription">
          {transcription}
          {sourceLabel && <div className="voice-msg__source">来源：{sourceLabel}</div>}
        </div>
      )}
    </div>
  )
}
