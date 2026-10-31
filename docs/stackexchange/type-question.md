> Source: https://api.stackexchange.com/docs/types/question
> Retrieved: 2026-10-31
> Covers: question object returned by /search/advanced

# Type question

## Discussion

        This type represents a question on one of the Stack Exchange sites, such as this famous RegEx question.

    This type is heavily inspired by the question page itself, and can optionally return comments and answers accordingly.

        The upvoted, downvoted, and favorited fields can only be queried for with an access_token with the private_info scope.

## Fields

         accepted_answer_id

        integer

may be absent

         answer_count

        integer

         answers

        an array of answers

may be absent

         body

        string

unchanged in unsafe filters

         body_markdown 2.2

        string

         bounty_amount

        integer

may be absent

         bounty_closes_date

        date

may be absent

         bounty_user 2.2

        shallow_user

may be absent

         can_answer 2.3

        boolean

         can_close 2.2

        boolean

         can_comment 2.3

        boolean

         can_edit 2.3

        boolean

         can_flag 2.2

        boolean

         can_suggest_edit 2.3

        boolean

         close_vote_count 2.1

        integer

         closed_date

        date

may be absent

         closed_details 2.2

        closed_details

may be absent

         closed_reason

        string

may be absent

         collectives 2.3

        an array of collectives

         comment_count 2.2

        integer

         comments

        an array of comments

may be absent

         community_owned_date

        date

may be absent

         content_license 2.2

        string

         creation_date

        date

         delete_vote_count 2.1

        integer

         down_vote_count

        integer

         downvoted 2.2

        boolean

        private_info

         favorite_count

        integer

         favorited 2.2

        boolean

        private_info

         is_answered

        boolean

         last_activity_date

        date

         last_edit_date

        date

may be absent

         last_editor 2.2

        shallow_user

         link

        string

unchanged in unsafe filters

         locked_date

        date

may be absent

         migrated_from

        migration_info

may be absent

         migrated_to

        migration_info

may be absent

         notice 2.1

        notice

         owner

        shallow_user

may be absent

         posted_by_collectives 2.3

        an array of collectives

         protected_date

        date

may be absent

         question_id

        integer, refers to a question

         reopen_vote_count 2.1

        integer

         score

        integer

         share_link 2.2

        string

unchanged in unsafe filters

         tags

        an array of strings

         title

        string

         up_vote_count

        integer

         upvoted 2.2

        boolean

        private_info

         view_count

        integer

        Fields marked with  are included in the default filter, those marked with
         are excluded in the default filter.

## Examples

### ► Typical Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"answer_count":0,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Answered Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":true,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"answer_count":1,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Question With Accepted Answer

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":true,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"accepted_answer_id":2,"answer_count":1,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Closed Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"closed_date":1793450986,"answer_count":0,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","closed_reason":"not a real question","title":"An example post title","body":"An example post body"}

### ► Locked Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"answer_count":0,"score":1,"locked_date":1793454586,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Bountied Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"bounty_amount":500,"bounty_closes_date":1793810986,"answer_count":0,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Community Owned Question

        {"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"answer_count":0,"community_owned_date":1793461786,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Question Migrated From Other Site

        {"migrated_from":{"other_site":{"launch_date":1793465386,"open_beta_date":1793378986,"closed_beta_date":1793292586,"site_state":"normal","icon_url":"https://cdn.sstatic.net/stackexchange/Img/apple-touch-icon.png","audience":"example lovers","site_url":"https://example.stackexchange.com","api_site_parameter":"example","logo_url":"https://cdn.sstatic.net/stackexchange/Img/logo.png","name":"Example Site","site_type":"main_site"},"on_date":1793382586,"question_id":4321},"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"answer_count":0,"score":1,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","title":"An example post title","body":"An example post body"}

### ► Question Migrated To Other Site

        {"migrated_to":{"other_site":{"launch_date":1793465386,"open_beta_date":1793378986,"closed_beta_date":1793292586,"site_state":"normal","icon_url":"https://cdn.sstatic.net/stackexchange/Img/apple-touch-icon.png","audience":"example lovers","site_url":"https://example.stackexchange.com","api_site_parameter":"example","logo_url":"https://cdn.sstatic.net/stackexchange/Img/logo.png","name":"Example Site","site_type":"main_site"},"on_date":1793450986,"question_id":4321},"tags":["windows","c#",".net"],"owner":{"reputation":9001,"user_id":1,"user_type":"registered","accept_rate":55,"profile_image":"https://www.gravatar.com/avatar/a007be5a61f6aa8f3e85ae2fc18dd66e?d=identicon&r=PG","display_name":"Example User","link":"https://example.stackexchange.com/users/1/example-user"},"is_answered":false,"view_count":31415,"favorite_count":1,"down_vote_count":2,"up_vote_count":3,"closed_date":1793450986,"answer_count":0,"score":1,"locked_date":1793450986,"last_activity_date":1793422186,"creation_date":1793378986,"last_edit_date":1793447386,"question_id":1234,"link":"https://example.stackexchange.com/questions/1234/an-example-post-title","closed_reason":"off topic","title":"An example post title","body":"An example post body"}

## Methods That Return This Type

    answers/{ids}/questions 2.2
articles/{ids}/linked 2.3
collectives/{slugs}/questions 2.3
questions
questions/{ids}
questions/{ids}/linked
questions/{ids}/related
questions/unanswered
questions/unanswered/my-tags 2.2
questions/no-answers
questions/featured
questions/render 2.2
questions/{id}/flags/add 2.2
questions/{id}/favorite 2.2
questions/{id}/favorite/undo 2.2
questions/{id}/downvote/undo 2.2
questions/{id}/downvote 2.2
questions/{id}/upvote/undo 2.2
questions/{id}/upvote 2.2
questions/{id}/delete 2.2
questions/{id}/edit 2.2
questions/add 2.2
search/advanced 2.1
search
similar
tags/{tags}/faq
users/{ids}/favorites
users/{ids}/questions
users/{ids}/questions/no-answers
users/{ids}/questions/unaccepted
users/{ids}/questions/unanswered
users/{ids}/questions/featured
users/{id}/tags/{tags}/top-questions
me/favorites
me/questions
me/questions/no-answers
me/questions/unaccepted
me/questions/unanswered
me/questions/featured
me/tags/{tags}/top-questions
