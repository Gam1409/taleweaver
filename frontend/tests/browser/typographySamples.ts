const samples: Record<string, string> = {
  English: 'Evening light falls across the archive shelves. A sealed letter rests beside the coastal chart.\n\nMira: "You found the letter. Shall we read it together?"',
  Russian: 'Вечерний свет ложится на полки архива. Рядом с картой побережья лежит запечатанное письмо.\n\nMira: "Ты нашёл письмо. Прочитаем его вместе?"',
  Arabic: 'ينساب ضوء المساء على رفوف الأرشيف. وبجانب خريطة الساحل رسالة مختومة.\n\nMira: "لقد وجدت الرسالة. هل نقرؤها معًا؟"',
  Japanese: '夕暮れの光が書庫の棚を照らしている。海岸の地図のそばに、封をされた手紙が置かれている。\n\nMira: "手紙を見つけたのね。一緒に読んでみましょうか。"',
  Chinese: '傍晚的光落在档案室的书架上。海岸地图旁放着一封密封的信。\n\nMira: "你找到那封信了。我们一起读吧？"',
  'Traditional Chinese': '傍晚的光落在檔案室的書架上。海岸地圖旁放著一封密封的信。\n\nMira: "你找到那封信了。我們一起讀吧？"',
  Korean: '저녁 햇살이 기록 보관소의 선반을 비춘다. 해안 지도 옆에는 봉인된 편지 한 통이 놓여 있다.\n\nMira: "편지를 찾았군요. 함께 읽어 볼까요?"'
}

export function sampleReply(language: string): string {
  return samples[language] || samples.English!
}
