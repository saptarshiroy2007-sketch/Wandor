package com.wandor.app.api

import retrofit2.Call
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST

data class FlagEventRequest(
    val attemptId: String,
    val eventType: String,
    val timestamp: String = java.time.Instant.now().toString()
)

interface TestService {
    @POST("tests/attempts/flag")
    fun flagAttempt(@Body req: FlagEventRequest): Call<Map<String, Any>>
}

object ApiClient {
    private const val BASE_URL = "https://your-backend-domain.com/" // point at your FastAPI deployment

    private val retrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val testService: TestService = retrofit.create(TestService::class.java)
}
