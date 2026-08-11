import { ApiProperty } from "@nestjs/swagger";

export class ErrorResponseDto {
  @ApiProperty({ example: 400 })
  statusCode!: number;

  @ApiProperty({ example: "Bad Request" })
  message!: string;

  @ApiProperty({ example: "VALIDATION_ERROR" })
  code!: string;

  @ApiProperty({ example: "2026-08-11T06:57:00.000Z" })
  timestamp!: string;

  @ApiProperty({ example: "req_abc123" })
  requestId!: string;

  @ApiProperty({ example: "/api/v1/some-path" })
  path!: string;
}
