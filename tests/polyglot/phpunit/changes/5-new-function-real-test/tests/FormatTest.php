<?php

declare(strict_types=1);

namespace Shop\Tests;

use PHPUnit\Framework\TestCase;
use Shop\Pricing;

final class FormatTest extends TestCase
{
    public function testShowsCentsAsEurosWithTwoDecimals(): void
    {
        $this->assertSame('12.50', Pricing::formatPrice(1250));
    }
}
