import ReactMarkdown from 'react-markdown'
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import secureAxios from '../utils/secureAxios';

const Chat = () => {
  const [message, setMessage] = useState('');
  const [chat, setChat] = useState([]);
  const [chatsList, setChatsList] = useState([]);
  const chatEndRef = useRef(null);
  const [isTyping, setIsTyping] = useState(false)
  const [activeChatId, setActiveChatId] = useState(null);

  
  const send = async () => {
    const email = localStorage.getItem('email');
    if (!activeChatId) return alert("Select or create a chat first.");
  
    try {
      // Save user message
      // await axios.post(`http://localhost:8000/api/v1/chat/${activeChatId}/message`, {
      //   chat_id: activeChatId,
      //   role: 'user',
      //   content: message,
      // });
      //await secureAxios.post(`http://localhost:8000/api/v1/chat/${activeChatId}/message`, {
        await secureAxios.post(`/chat/${activeChatId}/message`, {        
          chat_id: activeChatId,
          role: 'user',
          content: message,
        });

      setChat(prev => [...prev, { role: 'user', content: message }]);
      setMessage('');
      setIsTyping(true);
  
      // Simulate assistant reply (or call GPT logic)
      //const res = await secureAxios.post(`http://localhost:8000/api/v1/chat/${activeChatId}/message`, {
      const res = await secureAxios.post(`/chat/${activeChatId}/message`, {
        chat_id: activeChatId,
        role: 'assistant',
        content: `Echo: ${message}`, // Replace with GPT call later
      });
  
      setChat(prev => [...prev, res.data]);
    } catch (err) {
      console.error("Send failed:", err);
    } finally {
      setIsTyping(false);
    }
  };
    
  const newChat = async () => {
    const email = localStorage.getItem('email');
    try {
      //const res = await secureAxios.post('http://localhost:8000/api/v1/chat', new URLSearchParams({
      const res = await secureAxios.post('/chat', new URLSearchParams({
        user_email: email,
        message: 'New chat started'  // required by your POST /chat route
      }));
      const { session_id } = res.data;
  
      setActiveChatId(session_id);
      setChat([]);
      fetchChats(); // optionally refresh chat list in sidebar
    } catch (err) {
      console.error("Failed to create new chat:", err);
    }
  };
  
  
  const loadChat = async (chatId) => {
    try {
      //const res = await secureAxios.get(`http://localhost:8000/api/v1/chat/${chatId}`);
      const res = await secureAxios.get(`/chat/${chatId}`);
      setChat(res.data);
      setActiveChatId(chatId);  // ✅ track the chat
    } catch (err) {
      console.error("Failed to load chat messages:", err);
    }
  };
  

  useEffect(() => {
    const fetchChats = async () => {
      // const email = localStorage.getItem('email');
      const email = localStorage.getItem('email');
      if (!email) {
        console.warn("No email found in localStorage");
        return;
      }

      try {
        //const res = await secureAxios.get(`http://localhost:8000/api/v1/chat/sessions`, {
          const res = await secureAxios.get(`/chat/sessions`, {
          params: { user_email: email }
        });
        setChatsList(res.data); // [{ id, title, created_at }]
      } catch (err) {
        console.error('Failed to fetch chats', err);
      }
    };
  
    fetchChats();
  }, []);
  

  // Auto-scroll to bottom when new messages appear
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chat]);

  return (
    <div className="flex h-[calc(100vh-60px)]">
     


      {/* Left Pane */}
      <div className="w-1/4 bg-white border-r p-4 flex flex-col">
      
      
  {/* New Chat + Chat List stays the same */}

        <button
          onClick={newChat}
          className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 mb-4"
        >
          + New Chat
        </button>
      



      <div className="overflow-y-auto flex-grow">
        <h2 className="text-lg font-semibold mb-2">Chats</h2>
        
        <ul className="space-y-2">
          {/* Current Chat */}
         
          {activeChatId && (
            <li className="p-2 bg-green-100 rounded font-semibold text-green-900 border border-green-300">
              🟢 {
                chatsList.find(chat => chat.id === activeChatId)?.title || "Current Chat"
              }
            </li>
          )}


          {/* Other Chats */}
          {chatsList.map(chat => (
            <li
              key={chat.id}
              onClick={() => loadChat(chat.id)}
              className="p-2 bg-gray-100 rounded hover:bg-gray-200 cursor-pointer"
            >
              {chat.title}
            </li>
          ))}
        </ul>


      </div>

        
      </div>

      {/* Right Pane */}
      <div className="flex-1 flex flex-col bg-gray-50">
        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
            {activeChatId ? (
              <>
                {chat.map((m, i) => (
                  <div
                    key={i}
                    className={`p-3 rounded max-w-xl ${
                      m.role === 'user' ? 'bg-blue-100 self-end' : 'bg-gray-200 self-start'
                    }`}
                  >
                    <strong>{m.role === 'user' ? 'You' : 'Neura'}:</strong>
                    {m.role === 'bot' ? (
                      <div className="prose prose-sm">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    ) : (
                      <span>{m.content}</span>
                    )}
                  </div>
                ))}

                {isTyping && (
                  <div className="p-3 rounded max-w-xl bg-gray-200 self-start italic text-gray-500">
                    Neura is thinking...
                  </div>
                )}

                <div ref={chatEndRef} />
              </>
            ) : (
              <div className="text-center text-gray-500 mt-10 text-lg italic">
                👋 Welcome to Neura. Click <strong>+ New Chat</strong> or select a conversation to begin.
              </div>
            )}
          </div>


        {/* Input Section (Sticky Bottom) */}
        <div className="sticky bottom-0 bg-gray-50 px-4 py-3 border-t flex gap-2">
        <input
          value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && message.trim().length > 0 && activeChatId) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask something..."
          disabled={!(activeChatId && String(activeChatId).length > 0)}
          className={`flex-1 p-2 border rounded ${
            !(activeChatId && String(activeChatId).length > 0)
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : ''
          }`}
        />



          {/* <button
            onClick={send}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Send
          </button> */}

          <button
            onClick={send}
            disabled={!activeChatId || message.trim().length === 0}
            className={`px-4 py-2 text-white rounded ${
              activeChatId && message.trim().length > 0
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'bg-gray-400 cursor-not-allowed'
            }`}
          >
            Send
          </button>


        </div>
      </div>
    </div>
  );
};

export default Chat;
