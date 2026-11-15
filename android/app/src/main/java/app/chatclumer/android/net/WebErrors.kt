package app.chatclumer.android.net

enum class PageProblem { UNAUTHORIZED, RATE_LIMITED, UNAVAILABLE, OFFLINE }

object WebErrors {
    fun fromHttpStatus(status: Int): PageProblem? = when (status) {
        401 -> PageProblem.UNAUTHORIZED
        429 -> PageProblem.RATE_LIMITED
        in 400..599 -> PageProblem.UNAVAILABLE
        else -> null
    }
}
